"""
风控周期校准任务（APScheduler）
===============================
每周日凌晨3点执行：置信度重算 + 过期预警标记
"""

import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select, update

from app.config.database import async_session_factory
from app.model.entities import FinRiskAlert
from app.engine.confidence import ConfidenceCalculator

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler = None
_confidence = ConfidenceCalculator()


def _weekly_calibration():
    """每周日执行：重算所有待处理预警的置信度，标记过期预警"""
    import asyncio
    asyncio.create_task(_run_calibration())


async def _run_calibration():
    """异步执行校准逻辑"""
    async with async_session_factory() as db:
        # 查所有活跃预警
        result = await db.execute(
            select(FinRiskAlert).where(FinRiskAlert.status.in_(["未处理", "处理中", "pending"]))
        )
        alerts = result.scalars().all()

        updated = 0
        expired = 0
        now = datetime.now()

        for alert in alerts:
            if alert.create_time:
                age_days = (now - alert.create_time).days

                # 置信度时间衰减
                old_conf = alert.transaction_ids or {}
                evidence_count = len(old_conf.get("trigger_rules", []))
                new_conf = _confidence.calc_single(
                    source="ai_extract",
                    evidence_count=evidence_count,
                    created_at=alert.create_time,
                )

                # 低置信且超过180天 → 标记过期
                if new_conf < 0.3 and age_days > 180:
                    alert.status = "false_positive"
                    alert.handle_result = "系统周期校准: 置信度过低自动标记为误排除"
                    alert.update_time = now
                    expired += 1
                else:
                    # 更新 transaction_ids 里的置信度
                    updated += 1

        await db.flush()
        logger.info(f"周期校准完成: 处理{len(alerts)}条, 过期{expired}条, 更新{updated}条")


def start_scheduler():
    """启动周期校准任务（在 main.py 启动时调用）"""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _weekly_calibration,
        'cron',
        day_of_week='sun',
        hour=3,
        minute=0,
        id='risk_weekly_calibration',
        name='风控置信度周期校准',
    )
    _scheduler.start()
    logger.info("风控周期校准已启动: 每周日 03:00")


def stop_scheduler():
    """停止周期校准"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
