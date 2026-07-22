"""风险评估 API 路由"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.service.risk_service import RiskService
from app.model.schemas import AssessmentRequest, SuitabilityCheckRequest
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
