"""风险评估 API 路由"""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.service.risk_service import RiskService
from app.model.schemas import AssessmentRequest, SuitabilityCheckRequest, TransactionEvent, AlertHandleRequest
from app.utils.response import success, error
from app.utils.exceptions import ProfileNotFound

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/questionnaire")
async def get_questionnaire():
    """获取风评问卷（16道题）"""
    service = RiskService.__new__(RiskService)
    questionnaire = service.get_questionnaire()
    return success(data=[q.model_dump() for q in questionnaire])


@router.post("/assessment")
async def submit_assessment(req: AssessmentRequest, db: AsyncSession = Depends(get_db)):
    """提交风评答卷，计算风险等级"""
    service = RiskService(db)
    result = await service.submit_assessment(req.customer_id, req.answers)
    return success(data=result.model_dump(), message=f"风险评估完成，等级：{result.risk_level}")


@router.post("/suitability-check")
async def check_suitability(req: SuitabilityCheckRequest, db: AsyncSession = Depends(get_db)):
    """适当性匹配校验"""
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
from app.engine.confidence import ConfidenceCalculator

_monitor = RiskMonitorService()
_confidence = ConfidenceCalculator()


@router.post("/monitor", summary="接收交易事件进行风控监测")
async def monitor_transaction(tx: TransactionEvent, db: AsyncSession = Depends(get_db)):
    """接收交易事件 → 20条规则匹配 → 预警分级 → 返回结果 + MySQL持久化 + 工单"""
    logger.info(f"风控监测: 客户{tx.customer_id}, 金额{tx.amount}, 类型{tx.transaction_type}")
    tx_dict = tx.model_dump()

    triggered = _monitor.evaluate_all(tx_dict)
    if not triggered:
        logger.debug(f"客户{tx.customer_id}交易正常，无规则触发")
        return success(data={"alert": None, "triggered_count": 0})

    logger.info(f"客户{tx.customer_id}触发{len(triggered)}条规则: {[r.rule_id for r in triggered]}")

    _, history = await _monitor.get_alerts(db, customer_id=tx.customer_id)
    level = _monitor.grade(triggered, history, tx_dict)
    logger.info(f"预警等级: {level}")

    conf = _confidence.calc_single(source="ai_extract", evidence_count=len(triggered))
    alert = _monitor.build_alert(tx_dict, triggered, level, conf)
    await _monitor.save_alert(db, alert)
    logger.info(f"预警已生成: level={level}, confidence={conf:.2f}")

    return success(data={"alert": alert, "triggered_count": len(triggered)})


@router.get("/alerts", summary="查询历史预警列表")
async def list_alerts(customer_id: int = None, alert_level: str = None,
                      status: str = None, days: int = 30, page: int = 1,
                      page_size: int = 20, db: AsyncSession = Depends(get_db)):
    """查询历史预警，支持筛选和分页"""
    total, alerts = await _monitor.get_alerts(db, customer_id, alert_level, status, days, page, page_size)
    return success(data={"total": total, "page": page, "page_size": page_size, "alerts": alerts})


@router.get("/alert/{alert_id}", summary="查看预警详情")
async def get_alert_detail(alert_id: str, db: AsyncSession = Depends(get_db)):
    """查看单条预警详情"""
    alert = await _monitor.get_alert(db, alert_id)
    if not alert:
        return error(404, f"预警 {alert_id} 不存在")
    return success(data=alert)


@router.put("/alert/{alert_id}/handle", summary="处理预警")
async def handle_alert(alert_id: str, req: AlertHandleRequest, db: AsyncSession = Depends(get_db)):
    """风控专员处理预警"""
    logger.info(f"处理预警: id={alert_id}, action={req.action}, handler={req.handler_id}")
    alert = await _monitor.handle_alert(db, alert_id, req.action, req.handler_id, req.handle_note)
    if not alert:
        return error(404, f"预警 {alert_id} 不存在")
    logger.info(f"预警 {alert_id} 处理完成: {req.action}")
    return success(data={"alert_id": alert_id, "status": req.action})


@router.post("/recalculate", summary="手动触发置信度重算")
async def recalculate_confidence(customer_id: int = None, db: AsyncSession = Depends(get_db)):
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


@router.get("/profile/{customer_id}", summary="查客户风险画像")
async def get_risk_profile(customer_id: int, db: AsyncSession = Depends(get_db)):
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
