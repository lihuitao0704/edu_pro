"""风险评估 API 路由"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.service.risk_service import RiskService
from app.model.schemas import AssessmentRequest, SuitabilityCheckRequest, TransactionEvent, AlertHandleRequest
from app.utils.response import success, error
from app.utils.exceptions import ProfileNotFound

router = APIRouter()


@router.get("/questionnaire")
async def get_questionnaire():
    """获取风评问卷（16道题）"""
    service = RiskService.__new__(RiskService)  # 无需 db session
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
def monitor_transaction(tx: TransactionEvent):
    """接收交易事件 → 20条规则匹配 → 预警分级 → 返回结果"""
    tx_dict = tx.model_dump()

    # 1. 规则匹配
    triggered = _monitor.evaluate_all(tx_dict)
    if not triggered:
        return success(data={"alert": None, "triggered_count": 0})

    # 2. 查历史预警
    history = _monitor.get_alerts(customer_id=tx.customer_id)[1]

    # 3. 分级
    level = _monitor.grade(triggered, history, tx_dict)

    # 4. 置信度（复用团队引擎）
    conf = _confidence.calc_single(source="ai_extract", evidence_count=len(triggered))

    # 5. 生成 + 存储
    alert = _monitor.build_alert(tx_dict, triggered, level, conf)
    _monitor.save_alert(alert)

    return success(data={"alert": alert, "triggered_count": len(triggered)})


@router.get("/alerts", summary="查询历史预警列表")
def list_alerts(customer_id: int = None, alert_level: str = None,
                status: str = None, days: int = 30, page: int = 1, page_size: int = 20):
    """查询历史预警，支持筛选和分页"""
    total, alerts = _monitor.get_alerts(customer_id, alert_level, status, days, page, page_size)
    return success(data={"total": total, "page": page, "page_size": page_size, "alerts": alerts})


@router.get("/alert/{alert_id}", summary="查看预警详情")
def get_alert_detail(alert_id: str):
    """查看单条预警详情"""
    alert = _monitor.get_alert(alert_id)
    if not alert:
        return error(404, f"预警 {alert_id} 不存在")
    return success(data=alert)


@router.put("/alert/{alert_id}/handle", summary="处理预警")
def handle_alert(alert_id: str, req: AlertHandleRequest):
    """风控专员处理预警"""
    alert = _monitor.handle_alert(alert_id, req.action)
    if not alert:
        return error(404, f"预警 {alert_id} 不存在")
    return success(data={"alert_id": alert_id, "status": req.action})
