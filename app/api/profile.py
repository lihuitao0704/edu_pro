"""
画像分析与解释 API 路由
注册 ProfileAgent 和 ExplanationAgent，使其可通过 HTTP 调用。
提供画像查询（GET /{customer_id}）供前端客户画像页直接加载。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.profile_agent import ProfileAgent
from app.agent.explanation_agent import ExplanationAgent
from app.config.database import get_db
from app.security.authorization import enforce_customer_scope, require_roles
from app.service.profile_service import ProfileService
from app.utils.response import success, error
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class ProfileAnalyzeRequest(BaseModel):
    """画像分析请求"""
    message: str = "请分析该客户的风险画像"
    customer_id: int


class ExplainRequest(BaseModel):
    """解释请求"""
    message: str = "请解释推荐原因"
    customer_id: int


@router.get("/{customer_id}")
async def get_profile(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("理财顾问", "客户经理", "风控专员", "管理员", "客户")),
):
    """
    查询客户画像（前端 ProfileView 直接加载）

    先 Redis 缓存 → 后 MySQL → 回填缓存（Cache-Aside）。
    返回前端所需的全部画像字段：risk_level / risk_score / 四维度分 / total_assets 等。
    """
    # 客户只能查看自己的画像
    if user.get("role") == "客户" and int(user.get("user_id") or 0) != customer_id:
        raise HTTPException(status_code=403, detail="客户只能访问本人数据")

    try:
        service = ProfileService(db)
        profile = await service.get_profile(customer_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"客户 {customer_id} 的画像不存在")

        return success(data=service._profile_to_dict(profile))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"画像查询异常: {e}", exc_info=True)
        return error(500, f"画像查询服务异常: {str(e)}")


@router.post("/profile/analyze")
async def analyze_profile(
    req: ProfileAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("理财顾问", "管理员")),
):
    """
    画像分析接口（ProfileAgent）

    输入客户ID → 调用 ProfileService 获取画像 → LLM 生成可读的画像解读。
    """
    enforce_customer_scope(user, req.customer_id)

    try:
        agent = ProfileAgent(db=db)
        result = await agent.run(req.message, customer_id=req.customer_id)
        return success(data={
            "reply": result.get("reply", "分析完成"),
            "session_id": result.get("session_id", ""),
        })
    except Exception as e:
        logger.error(f"画像分析异常: {e}", exc_info=True)
        return error(500, f"画像分析服务异常: {str(e)}")


@router.post("/explain")
async def explain_recommendation(
    req: ExplainRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("理财顾问", "管理员")),
):
    """
    推荐解释接口（ExplanationAgent）

    输入客户ID → 获取画像和历史评分 → LLM 生成可读的推荐/风险解释。
    """
    enforce_customer_scope(user, req.customer_id)

    try:
        agent = ExplanationAgent(db=db)
        result = await agent.run(req.message, customer_id=req.customer_id)
        return success(data={
            "reply": result.get("reply", "解释完成"),
            "risk_level": result.get("risk_level"),
        })
    except Exception as e:
        logger.error(f"解释服务异常: {e}", exc_info=True)
        return error(500, f"解释服务异常: {str(e)}")
