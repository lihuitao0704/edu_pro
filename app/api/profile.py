"""画像 API 路由"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.service.profile_service import ProfileService
from app.model.schemas import (
    ProfileUpdateRequest, ProfileAssessRequest)
from app.utils.response import success, error
from app.utils.exceptions import ProfileNotFound, CircuitBreakerTriggered
from app.security.authorization import require_roles

router = APIRouter()


@router.get("/{customer_id}")
async def get_profile(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(
        require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")
    ),
):
    """查询客户画像（Cache-Aside）"""
    if user.get("role") == "客户" and int(user.get("user_id") or 0) != customer_id:
        return error(403, "客户只能访问本人画像")
    service = ProfileService(db)
    profile = await service.get_profile(customer_id)
    if not profile:
        return error(404, f"客户 {customer_id} 的画像不存在")

    return success(data={
        "customer_id": profile.customer_id,
        "risk_level": profile.risk_level,
        "risk_score": profile.risk_score,
        "confidence_score": str(profile.confidence_score) if profile.confidence_score else None,
        "basic_score": str(profile.basic_score) if profile.basic_score else None,
        "experience_score": str(profile.experience_score) if profile.experience_score else None,
        "risk_pref_score": str(profile.risk_pref_score) if profile.risk_pref_score else None,
        "behavior_score": str(profile.behavior_score) if profile.behavior_score else None,
        "total_assets": str(profile.total_assets) if profile.total_assets else None,
        "investment_experience": profile.investment_experience,
        "annual_income_range": profile.annual_income_range,
        "risk_flag": profile.risk_flag,
        "update_time": str(profile.update_time) if profile.update_time else None,
    })


@router.put("/{customer_id}")
async def update_profile(
    customer_id: int,
    req: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles("理财顾问", "管理员")),
):
    """增量更新客户画像标签"""
    service = ProfileService(db)
    result = await service.update_tags(customer_id, req.tags)
    return success(data=result, message=f"已更新 {result['updated_tags']} 个标签")


@router.post("/{customer_id}/assess")
async def assess_profile(
    customer_id: int,
    req: ProfileAssessRequest = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles("理财顾问", "管理员")),
):
    """
    执行画像研判打分

    流程: 接收ID → 调用画像引擎 → 四维度打分 → 检查熔断 → 返回JSON结果
    响应格式对齐文档 14.2 章节
    """
    # 路径参数优先，请求体中的 customer_id 作为备用（可选）
    trigger_type = req.trigger_type if req else "manual"
    assess_customer_id = customer_id  # 以路径参数为准

    service = ProfileService(db)
    try:
        result = await service.assess(assess_customer_id, trigger_type=trigger_type)
        return success(data=result.model_dump())
    except ProfileNotFound as e:
        return error(e.code, e.message)
    except CircuitBreakerTriggered as e:
        return error(e.code, e.message)
    except Exception as e:
        return error(500, f"研判失败: {str(e)}")
