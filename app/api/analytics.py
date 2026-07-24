from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common_services.analytics_service.analytics_service import ChatAnalyticsService
from app.config.database import get_db
from app.model.entities import FinAgentTrace, FinChatMetricDaily, FinChatSession
from app.security.authorization import authenticated_actor_id, require_roles
from app.utils.response import success

router = APIRouter()


@router.get("/analytics/chat/stats", response_model=dict)
async def chat_stats(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("管理员")),
):
    rows = (await db.execute(select(FinChatMetricDaily))).scalars().all()
    today_start = datetime.combine(date.today(), time.min)
    today_sessions = (await db.execute(
        select(func.count()).select_from(FinChatSession).where(FinChatSession.create_time >= today_start)
    )).scalar_one()
    return success(data=ChatAnalyticsService.aggregate(rows, int(today_sessions or 0)))


@router.get("/analytics/chat/traces", response_model=dict)
async def list_traces(
    session_id: str = "", agent_name: str = "", status: str = "",
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")),
):
    statement = select(FinAgentTrace)
    if str(user.get("role")) != "管理员":
        statement = statement.where(FinAgentTrace.user_id == authenticated_actor_id(user))
    if session_id:
        statement = statement.where(FinAgentTrace.session_id == session_id)
    if agent_name:
        statement = statement.where(FinAgentTrace.target_agent == agent_name)
    if status:
        statement = statement.where(FinAgentTrace.status == status)
    traces = (await db.execute(statement.order_by(FinAgentTrace.created_time.desc()).limit(100))).scalars().all()
    return success(data={"items": [{
        "trace_id": item.trace_id, "session_id": item.session_id,
        "agent_name": item.target_agent, "status": item.status,
        "created_time": item.created_time.isoformat() if item.created_time else None,
    } for item in traces]})


@router.get("/analytics/chat/traces/{trace_id}", response_model=dict)
async def get_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")),
):
    trace = await db.get(FinAgentTrace, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    if str(user.get("role")) != "管理员" and int(trace.user_id) != authenticated_actor_id(user):
        raise HTTPException(status_code=403, detail="cannot access another user's trace")
    return success(data={
        "trace_id": trace.trace_id, "session_id": trace.session_id,
        "intent": trace.intent, "agent_name": trace.target_agent,
        "status": trace.status, "input_masked": trace.input_masked,
        "output_masked": trace.output_masked,
        "created_time": trace.created_time.isoformat() if trace.created_time else None,
    })


# ════════════════════════════════════════════════════════════
# BI 仪表盘 — 6 个业务指标的预聚合数据
# ════════════════════════════════════════════════════════════

_DASHBOARD_SQL = {
    # ① AUM分布：各风险等级的总资产占比
    "aum_distribution": text("""
        SELECT
            COALESCE(risk_level, '未知') AS name,
            COUNT(*)                     AS customer_count,
            ROUND(COALESCE(SUM(total_assets), 0), 2) AS total_aum,
            ROUND(COALESCE(AVG(total_assets), 0), 2) AS avg_aum
        FROM fin_customer_profile
        GROUP BY risk_level
        ORDER BY total_aum DESC
    """),
    # ② 各风险等级产品平均收益率
    "return_by_risk": text("""
        SELECT
            COALESCE(risk_level, '未知') AS name,
            COUNT(*)                     AS product_count,
            ROUND(COALESCE(AVG(expected_return), 0), 2) AS avg_return,
            ROUND(COALESCE(MIN(expected_return), 0), 2) AS min_return,
            ROUND(COALESCE(MAX(expected_return), 0), 2) AS max_return
        FROM fin_product
        WHERE status = '在售'
        GROUP BY risk_level
        ORDER BY risk_level
    """),
    # ③ 热销产品 Top10
    "top_products": text("""
        SELECT
            p.product_name,
            p.product_type,
            p.risk_level,
            COUNT(t.id)                     AS tx_count,
            ROUND(COALESCE(SUM(t.amount), 0), 2) AS total_amount
        FROM fin_transaction t
        JOIN fin_product p ON t.product_id = p.id
        WHERE t.transaction_type IN ('purchase', '申购')
        GROUP BY p.id, p.product_name, p.product_type, p.risk_level
        ORDER BY total_amount DESC
        LIMIT 10
    """),
    # ④ 月度交易趋势（近12个月）
    "monthly_trend": text("""
        SELECT
            DATE_FORMAT(create_time, '%Y-%m') AS month,
            transaction_type,
            COUNT(*)                          AS tx_count,
            ROUND(COALESCE(SUM(amount), 0), 2)     AS total_amount
        FROM fin_transaction
        WHERE create_time >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
        GROUP BY DATE_FORMAT(create_time, '%Y-%m'), transaction_type
        ORDER BY month, transaction_type
    """),
    # ⑤ 风险预警分布
    "alert_distribution": text("""
        SELECT
            alert_level AS name,
            COUNT(*)    AS count,
            CASE alert_level
                WHEN 'high'   THEN '🔴 高'
                WHEN 'medium' THEN '🟡 中'
                WHEN 'low'    THEN '🔵 低'
                ELSE alert_level
            END AS label
        FROM fin_risk_alert
        GROUP BY alert_level
        ORDER BY FIELD(alert_level, 'high', 'medium', 'low')
    """),
    # ⑥ 产品货架矩阵
    "product_matrix": text("""
        SELECT
            COALESCE(product_type, '其他') AS product_type,
            COALESCE(risk_level, '未知')  AS risk_level,
            COUNT(*)                      AS product_count
        FROM fin_product
        WHERE status = '在售'
        GROUP BY product_type, risk_level
        ORDER BY product_type, risk_level
    """),
}


def _rows_to_dict(rows: list) -> list[dict[str, Any]]:
    """Map a list of Row objects to plain dicts, converting Decimals to floats."""
    return [
        {
            col: (float(val) if isinstance(val, Decimal) else val)
            for col, val in row._mapping.items()
        }
        for row in rows
    ]


@router.get("/analytics/bi/dashboard")
async def bi_dashboard(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")),
):
    """BI 仪表盘聚合数据 —— 返回 6 个预计算业务指标"""
    results: dict[str, Any] = {}

    for key, stmt in _DASHBOARD_SQL.items():
        try:
            rows = (await db.execute(stmt)).all()
            results[key] = _rows_to_dict(rows) if rows else []
        except Exception as e:
            results[key] = []
            import logging
            logging.getLogger(__name__).warning("BI query [%s] failed: %s", key, e)

    # 补充汇总统计
    results["summary"] = _compute_summary(results)

    return success(data=results)


def _compute_summary(data: dict) -> dict:
    """汇总统计：客户数、总AUM、在售产品数、预警总数"""
    aum_rows = data.get("aum_distribution", [])
    alert_rows = data.get("alert_distribution", [])
    product_rows = data.get("product_matrix", [])

    total_customers = sum(r.get("customer_count", 0) for r in aum_rows)
    total_aum = sum(r.get("total_aum", 0) for r in aum_rows)
    total_alerts = sum(r.get("count", 0) for r in alert_rows)
    in_sale_products = sum(r.get("product_count", 0) for r in product_rows)

    return {
        "total_customers": total_customers,
        "total_aum": round(total_aum, 2),
        "in_sale_products": in_sale_products,
        "total_alerts": total_alerts,
    }
