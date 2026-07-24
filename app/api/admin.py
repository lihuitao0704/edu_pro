"""
管理接口 — 健康检查 / 可观测性 / 规则热加载
"""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db, get_neo4j_driver
from app.config.settings import get_settings
from app.security.authorization import require_roles
from app.utils.response import success, error

router = APIRouter()
logger = logging.getLogger(__name__)
_settings = get_settings()

# ── 可观测性计数器（Issue #7 修复）──
_metrics = {
    "neo4j_sync_failures": 0,
    "neo4j_sync_successes": 0,
    "memory_recall_failures": 0,
    "agent_timeouts": 0,
    "agent_errors": 0,
    "profile_assess_failures": 0,
    "purchase_total": 0,
    "purchase_errors": 0,
}


def inc_metric(name: str) -> None:
    """增加计数器（线程安全，适用于低并发场景）"""
    if name in _metrics:
        _metrics[name] += 1


def get_metrics() -> dict:
    return dict(_metrics)


# ═══════════════════════════════════════════════════════════
# 健康检查（增强版 — Issue #7）
# ═══════════════════════════════════════════════════════════

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """全面健康检查：MySQL / Redis / Neo4j / LLM 连通性"""
    checks = {}

    # MySQL
    try:
        await db.execute(text("SELECT 1"))
        checks["mysql"] = "ok"
    except Exception as e:
        checks["mysql"] = f"error: {str(e)[:100]}"

    # Redis
    try:
        from app.config.database import get_redis
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:100]}"

    # Neo4j
    try:
        driver = get_neo4j_driver()
        async with driver.session(database=_settings.neo4j.database) as session:
            await session.run("RETURN 1")
        checks["neo4j"] = "ok"
    except Exception as e:
        checks["neo4j"] = f"error: {str(e)[:100]}"

    # 图谱同步积压
    try:
        pending = await db.execute(
            text("SELECT COUNT(*) FROM fin_graph_sync_retry WHERE status = 'pending'")
        )
        pending_count = pending.scalar() or 0
        manual = await db.execute(
            text("SELECT COUNT(*) FROM fin_graph_sync_retry WHERE status = 'manual_review'")
        )
        manual_count = manual.scalar() or 0
        checks["graph_sync_pending"] = pending_count
        checks["graph_sync_manual_review"] = manual_count
    except Exception:
        checks["graph_sync_pending"] = "n/a"

    # 整体状态
    all_ok = all(
        v == "ok" or isinstance(v, int)
        for k, v in checks.items()
        if k not in ("graph_sync_pending", "graph_sync_manual_review")
    )

    return success(data={
        "status": "healthy" if all_ok else "degraded",
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
        "metrics": get_metrics(),
    })


# ═══════════════════════════════════════════════════════════
# 可观测性指标
# ═══════════════════════════════════════════════════════════

@router.get("/metrics")
async def metrics_endpoint(
    _: dict = Depends(require_roles("管理员")),
):
    """返回系统可观测性指标"""
    return success(data={
        "metrics": get_metrics(),
        "timestamp": datetime.now().isoformat(),
    })


@router.post("/metrics/reset")
async def reset_metrics(
    _: dict = Depends(require_roles("管理员")),
):
    """重置可观测性计数器"""
    for key in _metrics:
        _metrics[key] = 0
    return success(message="指标已重置")


# ═══════════════════════════════════════════════════════════
# 规则热加载
# ═══════════════════════════════════════════════════════════

@router.post("/rules/reload")
async def reload_rules(
    _: dict = Depends(require_roles("管理员")),
):
    """热加载规则配置（从 risk_rule 表重新读取，无需重启服务）"""
    import importlib
    import app.config.rules_config as rc

    try:
        importlib.reload(rc)
        logger.info("规则配置已热加载")
        return success(message="规则配置已从代码重新加载（如需从DB加载请设置 RULE_LOADER_USE_DB=true）")
    except Exception as e:
        logger.error(f"规则热加载失败: {e}")
        return error(500, f"规则热加载失败: {str(e)}")


@router.get("/rules/status")
async def rules_status(
    _: dict = Depends(require_roles("管理员")),
):
    """查看当前规则加载状态"""
    from app.config.settings import get_settings
    use_db = get_settings().rule_loader.use_db
    return success(data={
        "rule_source": "database (risk_rule table)" if use_db else "code (rules_config.py)",
        "rule_loader_use_db": use_db,
        "hot_reload_supported": True,
    })


# ═══════════════════════════════════════════════════════════
# 图谱同步状态
# ═══════════════════════════════════════════════════════════

@router.get("/graph-sync/status")
async def graph_sync_status(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles("管理员")),
):
    """查看图谱同步积压和失败详情"""
    # 按状态统计
    result = await db.execute(
        text("""
            SELECT status, COUNT(*) as cnt
            FROM fin_graph_sync_retry
            GROUP BY status
        """)
    )
    by_status = {row.status: row.cnt for row in result.fetchall()}

    # 最近需要人工处理的
    manual = await db.execute(
        text("""
            SELECT id, sync_type, retry_count, error_message, created_at
            FROM fin_graph_sync_retry
            WHERE status = 'manual_review'
            ORDER BY created_at DESC LIMIT 10
        """)
    )
    manual_items = [
        {
            "id": row.id,
            "sync_type": row.sync_type,
            "retry_count": row.retry_count,
            "error": (row.error_message or "")[:200],
            "created_at": str(row.created_at) if row.created_at else None,
        }
        for row in manual.fetchall()
    ]

    return success(data={
        "by_status": by_status,
        "manual_review_items": manual_items,
    })
