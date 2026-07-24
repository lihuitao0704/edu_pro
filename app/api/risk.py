"""风险评估 API 路由"""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.service.risk_service import RiskService
from app.model.schemas import AssessmentRequest, SuitabilityCheckRequest, TransactionEvent, AlertHandleRequest
from app.utils.response import success, error
from app.utils.exceptions import ProfileNotFound
from app.security.authorization import (
    authenticated_actor_id,
    enforce_customer_scope,
    require_roles,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/questionnaire")
async def get_questionnaire():
    """获取风评问卷（16道题）"""
    service = RiskService.__new__(RiskService)
    questionnaire = service.get_questionnaire()
    return success(data=[q.model_dump() for q in questionnaire])


@router.post("/assessment")
async def submit_assessment(
    req: AssessmentRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """提交风评答卷，计算风险等级"""
    enforce_customer_scope(user, req.customer_id)
    service = RiskService(db)
    result = await service.submit_assessment(req.customer_id, req.answers)
    return success(data=result.model_dump(), message=f"风险评估完成，等级：{result.risk_level}")


@router.post("/suitability-check")
async def check_suitability(
    req: SuitabilityCheckRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """适当性匹配校验"""
    enforce_customer_scope(user, req.customer_id)
    service = RiskService(db)
    try:
        result = await service.check_suitability(req.customer_id, req.product_code)
        if result.match:
            return success(data=result.model_dump(), message="适当性匹配通过")
        else:
            return error(403, result.warning or "适当性不匹配", data=result.model_dump())
    except ProfileNotFound as e:
        return error(e.code, e.message)


# ═══════════════════════════════════════════════════════════
# Phase 4 — 风控监测
# ═══════════════════════════════════════════════════════════

from app.service.risk_monitor_service import RiskMonitorService
from app.service.transaction_flow_service import TransactionFlowService

_monitor = RiskMonitorService()
_transaction_flow = TransactionFlowService(monitor=_monitor)


@router.post("/monitor", summary="接收交易事件进行风控监测")
async def monitor_transaction(
    tx: TransactionEvent,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles("风控专员", "管理员")),
):
    """接收交易事件 → 20条规则匹配 → 预警分级 → 返回结果 + MySQL持久化 + 工单"""
    logger.info(f"风控监测: 客户{tx.customer_id}, 金额{tx.amount}, 类型{tx.transaction_type}")
    result = await _transaction_flow.monitor(db, tx.model_dump())
    if not result["alert"]:
        logger.debug(f"客户{tx.customer_id}交易正常，无规则触发")
    else:
        logger.info(
            "客户%s触发%s条规则，预警等级=%s",
            tx.customer_id,
            result["triggered_count"],
            result["alert"]["alert_level"],
        )
    return success(data=result)


@router.get("/alerts", summary="查询历史预警列表")
async def list_alerts(customer_id: int = None, alert_level: str = None,
                      status: str = None, days: int = 30, page: int = 1,
                      page_size: int = 20, db: AsyncSession = Depends(get_db),
                      _: dict = Depends(require_roles("风控专员", "管理员"))):
    """查询历史预警，支持筛选和分页"""
    total, alerts = await _monitor.get_alerts(db, customer_id, alert_level, status, days, page, page_size)
    return success(data={"total": total, "page": page, "page_size": page_size, "alerts": alerts})


@router.get("/alert/{alert_id}", summary="查看预警详情")
async def get_alert_detail(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles("风控专员", "管理员")),
):
    """查看单条预警详情"""
    alert = await _monitor.get_alert(db, alert_id)
    if not alert:
        return error(404, f"预警 {alert_id} 不存在")
    return success(data=alert)


@router.put("/alert/{alert_id}/handle", summary="处理预警")
async def handle_alert(
    alert_id: str,
    req: AlertHandleRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("风控专员", "管理员")),
):
    """风控专员处理预警"""
    handler_id = authenticated_actor_id(user)
    logger.info(f"处理预警: id={alert_id}, action={req.action}, handler={handler_id}")
    alert = await _monitor.handle_alert(
        db, alert_id, req.action, handler_id, req.handle_note
    )
    if not alert:
        return error(404, f"预警 {alert_id} 不存在")
    logger.info(f"预警 {alert_id} 处理完成: {req.action}")
    return success(data={"alert_id": alert_id, "status": req.action})


@router.post("/recalculate", summary="手动触发置信度重算")
async def recalculate_confidence(
    customer_id: int = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles("风控专员", "管理员")),
):
    """手动触发置信度重算"""
    logger.info(f"置信度重算触发: customer_id={customer_id or '全量'}")
    from app.service.risk_confidence_rank import FinalConfidenceRankTool
    ranker = FinalConfidenceRankTool()
    _, alerts = await _monitor.get_alerts(db, customer_id=customer_id)
    units = [{"confidence_score": a.get("confidence", 0.5), "age_days": 0,
              "semantic_similarity": 0.5, "historical_accuracy": 0.5,
              "conflict_count": 0} for a in alerts]
    if units:
        ranked = ranker.rank(units, "风险研判")
        logger.info(f"重算完成: {len(ranked)}条")
    return success(data={"processed": len(units)}, message="置信度重算完成")


@router.post("/monitor/batch", summary="批量交易风控扫描")
async def monitor_batch(
    transactions: list[TransactionEvent],
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles("风控专员", "管理员")),
):
    """批量接收交易事件 → 逐笔规则匹配 → 返回汇总报告（最多100笔）"""
    logger.info(f"批量风控扫描: 共{len(transactions)}笔")
    total = len(transactions)
    normal = 0
    alert_list = []
    high_count = medium_count = low_count = 0

    for tx in transactions[:100]:  # 上限100笔
        result = await _transaction_flow.monitor(db, tx.model_dump())
        if result["alert"] is None:
            normal += 1
        else:
            alert_list.append(result["alert"])
            level = result["alert"]["alert_level"]
            if level == "high": high_count += 1
            elif level == "medium": medium_count += 1
            else: low_count += 1

    return success(data={
        "total": total,
        "normal": normal,
        "alerts": len(alert_list),
        "high": high_count,
        "medium": medium_count,
        "low": low_count,
        "details": alert_list,
    })


@router.get("/report", summary="风控日报")
async def daily_report(date: str = None, db: AsyncSession = Depends(get_db),
                       _: dict = Depends(require_roles("风控专员", "管理员"))):
    """聚合当日风控数据：新增预警、已处理、待处理、高风险TOP5客户、触发最多规则TOP3"""
    from datetime import date as date_type
    from sqlalchemy import func, text as sa_text

    if date is None:
        target_date = date_type.today().isoformat()
    else:
        target_date = date

    # 今日新增预警
    result = await db.execute(
        sa_text(
            "SELECT alert_level, COUNT(*) as cnt FROM fin_risk_alert "
            "WHERE DATE(create_time) = :d GROUP BY alert_level"
        ),
        {"d": target_date},
    )
    level_counts = {row[0]: row[1] for row in result.fetchall()}
    total_new = sum(level_counts.values())

    # 今日已处理
    result = await db.execute(
        sa_text(
            "SELECT COUNT(*) FROM fin_risk_alert "
            "WHERE DATE(update_time) = :d AND status IN ('resolved','false_positive')"
        ),
        {"d": target_date},
    )
    resolved_today = result.fetchone()[0]

    # 当前待处理总数
    result = await db.execute(
        sa_text("SELECT COUNT(*) FROM fin_risk_alert WHERE status = 'pending'")
    )
    pending_total = result.fetchone()[0]

    # 高风险TOP5客户
    result = await db.execute(
        sa_text(
            "SELECT customer_id, COUNT(*) as cnt FROM fin_risk_alert "
            "WHERE alert_level = 'high' AND DATE(create_time) = :d "
            "GROUP BY customer_id ORDER BY cnt DESC LIMIT 5"
        ),
        {"d": target_date},
    )
    top_customers = [{"customer_id": row[0], "count": row[1]} for row in result.fetchall()]

    # 触发最多规则TOP3
    result = await db.execute(
        sa_text(
            "SELECT alert_type, COUNT(*) as cnt FROM fin_risk_alert "
            "WHERE DATE(create_time) = :d "
            "GROUP BY alert_type ORDER BY cnt DESC LIMIT 3"
        ),
        {"d": target_date},
    )
    top_rules = [{"rule_id": row[0], "count": row[1]} for row in result.fetchall()]

    return success(data={
        "date": target_date,
        "summary": {
            "total_alerts": total_new,
            "high_new": level_counts.get("high", 0),
            "medium_new": level_counts.get("medium", 0),
            "low_new": level_counts.get("low", 0),
            "resolved_today": resolved_today,
            "pending_total": pending_total,
        },
        "top_high_risk_customers": top_customers,
        "top_rules": top_rules,
    })


@router.get("/statistics", summary="预警趋势统计")
async def alert_statistics(days: int = 7, db: AsyncSession = Depends(get_db),
                           _: dict = Depends(require_roles("风控专员", "管理员"))):
    """返回近N天预警趋势和级别分布（前端图表用）"""
    from sqlalchemy import text as sa_text

    # 按日期统计预警数
    result = await db.execute(
        sa_text(
            "SELECT DATE(create_time) as d, COUNT(*) as cnt FROM fin_risk_alert "
            "WHERE create_time >= DATE_SUB(CURDATE(), INTERVAL :days DAY) "
            "GROUP BY DATE(create_time) ORDER BY d"
        ),
        {"days": days},
    )
    trend = [{"date": str(row[0]), "count": row[1]} for row in result.fetchall()]

    # 按级别分布
    result = await db.execute(
        sa_text("SELECT alert_level, COUNT(*) FROM fin_risk_alert GROUP BY alert_level")
    )
    level_dist = {row[0]: row[1] for row in result.fetchall()}

    return success(data={
        "trend": trend,
        "level_distribution": level_dist,
        "total": sum(level_dist.values()),
    })


@router.get("/alerts/export", summary="导出预警CSV")
async def export_alerts(from_date: str = None, to_date: str = None,
                        db: AsyncSession = Depends(get_db),
                        _: dict = Depends(require_roles("风控专员", "管理员"))):
    """导出预警记录为CSV文件（监管报送用）"""
    import csv, io
    from fastapi.responses import StreamingResponse
    from sqlalchemy import text as sa_text

    conditions = []
    params = {}
    if from_date:
        conditions.append("create_time >= :from_date")
        params["from_date"] = from_date
    if to_date:
        conditions.append("create_time <= :to_date")
        params["to_date"] = to_date + " 23:59:59"
    where = " AND ".join(conditions) if conditions else "1=1"

    result = await db.execute(
        sa_text(f"SELECT id, customer_id, alert_type, alert_level, trigger_detail, status, create_time, update_time FROM fin_risk_alert WHERE {where} ORDER BY create_time DESC"),
        params,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["预警编号", "客户ID", "触发规则", "预警级别", "触发详情", "状态", "创建时间", "更新时间"])
    for row in result.fetchall():
        writer.writerow(list(row))

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=risk_alerts_{from_date or 'all'}.csv"},
    )


@router.get("/profile/{customer_id}", summary="查客户风险画像")
async def get_risk_profile(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles("理财顾问", "风控专员", "管理员")),
):
    """查询客户风险画像（风控统计）"""
    _, alerts = await _monitor.get_alerts(db, customer_id=customer_id)
    count = len(alerts)
    last = alerts[0]["created_at"] if alerts else None
    return success(data={
        "customer_id": customer_id,
        "aml_risk_level": "high" if count >= 3 else "medium" if count >= 1 else "low",
        "alert_count_30d": count,
        "last_alert_at": last,
    })
