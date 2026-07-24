"""
图谱同步重试服务
================
MySQL commit 成功后 Neo4j 同步失败 → 写入 fin_graph_sync_retry 表
后台任务每 60 秒扫描并重试，超过 10 次失败标记为"需人工处理"
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text

from app.config.database import async_session_factory
from app.tool.neo4j_sync import sync_holding, sync_risk_level, remove_holding

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
MAX_RETRIES = 10
SCAN_INTERVAL_SECONDS = 60

# 同步操作映射
_SYNC_HANDLERS = {
    "holding": lambda payload: sync_holding(
        customer_id=payload["customer_id"],
        product_id=payload["product_id"],
        shares=payload["shares"],
        current_value=payload["current_value"],
    ),
    "risk_level": lambda payload: sync_risk_level(
        customer_id=payload["customer_id"],
        risk_level=payload["risk_level"],
    ),
    "remove_holding": lambda payload: remove_holding(
        customer_id=payload["customer_id"],
        product_id=payload["product_id"],
    ),
}


async def record_sync_failure(
    sync_type: str,
    payload: dict,
    error_message: str,
) -> int:
    """
    Neo4j 同步失败后写入重试表。
    返回插入的记录 ID。
    """
    async with async_session_factory() as db:
        result = await db.execute(
            text("""
                INSERT INTO fin_graph_sync_retry
                (sync_type, payload, error_message, retry_count, max_retries, next_retry_at, status)
                VALUES (:sync_type, :payload, :error_message, 0, :max_retries, NOW(), 'pending')
            """),
            {
                "sync_type": sync_type,
                "payload": json.dumps(payload, ensure_ascii=False),
                "error_message": str(error_message)[:1024],
                "max_retries": MAX_RETRIES,
            },
        )
        await db.commit()
        record_id = result.lastrowid
        logger.info(
            "图谱同步失败已记录 retry_id=%s type=%s error=%s",
            record_id, sync_type, str(error_message)[:100],
        )
        return record_id


async def _scan_and_retry() -> None:
    """扫描待重试记录，逐一重试。成功标记/失败累加/超限标记人工处理。"""
    async with async_session_factory() as db:
        # 查询所有 pending 状态且到了重试时间的记录
        result = await db.execute(
            text("""
                SELECT id, sync_type, payload, retry_count, max_retries
                FROM fin_graph_sync_retry
                WHERE status = 'pending'
                  AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                ORDER BY id ASC
                LIMIT 50
            """)
        )
        rows = result.fetchall()

        if not rows:
            return

        logger.info("图谱同步重试扫描: 待处理 %d 条", len(rows))

        for row in rows:
            retry_id = row.id
            sync_type = row.sync_type
            retry_count = row.retry_count
            max_retries = row.max_retries or MAX_RETRIES

            payload = row.payload
            if isinstance(payload, str):
                payload = json.loads(payload)

            handler = _SYNC_HANDLERS.get(sync_type)
            if handler is None:
                # 未知同步类型，直接标记人工处理
                await db.execute(
                    text("UPDATE fin_graph_sync_retry SET status = 'manual_review', error_message = :msg WHERE id = :id"),
                    {"id": retry_id, "msg": f"未知同步类型: {sync_type}"},
                )
                await db.commit()
                continue

            try:
                await handler(payload)
                # 成功 → 标记成功
                await db.execute(
                    text("UPDATE fin_graph_sync_retry SET status = 'success', updated_at = NOW() WHERE id = :id"),
                    {"id": retry_id},
                )
                await db.commit()
                logger.info("图谱同步重试成功 retry_id=%s type=%s", retry_id, sync_type)
            except Exception as exc:
                new_count = retry_count + 1
                error_msg = str(exc)[:1024]
                if new_count >= max_retries:
                    # 超过最大重试次数 → 需人工处理
                    await db.execute(
                        text("""
                            UPDATE fin_graph_sync_retry
                            SET retry_count = :cnt, error_message = :msg,
                                status = 'manual_review', updated_at = NOW()
                            WHERE id = :id
                        """),
                        {"id": retry_id, "cnt": new_count, "msg": error_msg},
                    )
                    logger.error(
                        "图谱同步重试耗尽 retry_id=%s type=%s count=%d → 需人工处理",
                        retry_id, sync_type, new_count,
                    )
                else:
                    # 累加重试次数，60秒后再试
                    next_retry = datetime.now() + timedelta(seconds=SCAN_INTERVAL_SECONDS)
                    await db.execute(
                        text("""
                            UPDATE fin_graph_sync_retry
                            SET retry_count = :cnt, error_message = :msg,
                                next_retry_at = :next, updated_at = NOW()
                            WHERE id = :id
                        """),
                        {
                            "id": retry_id,
                            "cnt": new_count,
                            "msg": error_msg,
                            "next": next_retry,
                        },
                    )
                    logger.warning(
                        "图谱同步重试失败 retry_id=%s type=%s count=%d/%d → 下次重试 %s",
                        retry_id, sync_type, new_count, max_retries,
                        next_retry.strftime("%H:%M:%S"),
                    )
                await db.commit()


def _scan_and_retry_sync():
    """同步包装器，供 APScheduler 调用"""
    asyncio.run(_scan_and_retry())


def start_graph_sync_retry_scheduler():
    """启动图谱同步重试后台任务（每 60 秒执行一次）"""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _scan_and_retry_sync,
        "interval",
        seconds=SCAN_INTERVAL_SECONDS,
        id="graph_sync_retry",
        name="图谱同步失败重试补偿",
        next_run_time=datetime.now() + timedelta(seconds=10),  # 启动后 10 秒首次执行
    )
    _scheduler.start()
    logger.info("图谱同步重试调度器已启动: 每 %d 秒扫描一次, 最大重试 %d 次", SCAN_INTERVAL_SECONDS, MAX_RETRIES)


def stop_graph_sync_retry_scheduler():
    """停止图谱同步重试调度器"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("图谱同步重试调度器已停止")
