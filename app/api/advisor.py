"""投顾对话 API 路由"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.agent.profile_agent import ProfileAgent
from app.agent.recommendation_agent import RecommendationAgent
from app.agent.explanation_agent import ExplanationAgent
from app.model.schemas import AdvisorChatRequest, RecommendRequest, AllocationRequest
from app.utils.response import success, error

router = APIRouter()


@router.post("/advisor")
async def advisor_chat(req: AdvisorChatRequest, db: AsyncSession = Depends(get_db)):
    """
    投顾对话接口
    根据消息意图自动路由到对应的 Agent（画像/推荐/解释）
    """
    if not req.customer_id:
        return error(400, "缺少 customer_id 参数")

    message = req.message

    try:
        # 意图识别 → 路由 Agent
        if "配置" in message or "资产配置" in message:
            agent = RecommendationAgent(db, req.session_id)
            result = await agent.execute(message, customer_id=req.customer_id)
        elif "推荐" in message or "产品" in message:
            agent = RecommendationAgent(db, req.session_id)
            result = await agent.execute(message, customer_id=req.customer_id, top_n=3)
        elif "为什么" in message or "解释" in message or "原因" in message:
            agent = ExplanationAgent(db, req.session_id)
            result = await agent.execute(message, customer_id=req.customer_id)
        elif "画像" in message or "研判" in message or "评估" in message or "标签" in message:
            agent = ProfileAgent(db, req.session_id)
            result = await agent.execute(message, customer_id=req.customer_id)
        else:
            # 默认：查询画像 + 推荐
            profile_agent = ProfileAgent(db, req.session_id)
            profile_result = await profile_agent.execute("查询客户画像", customer_id=req.customer_id)

            rec_agent = RecommendationAgent(db, req.session_id)
            rec_result = await rec_agent.execute("推荐产品", customer_id=req.customer_id)

            result = {
                "reply": f"{profile_result['reply']}\n\n{rec_result['reply']}",
                "recommendations": rec_result.get("recommendations", []),
                "customer_profile": rec_result.get("customer_profile"),
                "reasoning": rec_result.get("reasoning"),
            }

        return success(
            data={
                "reply": result.get("reply", "处理完成"),
                "recommendations": result.get("recommendations", []),
                "customer_profile": result.get("customer_profile"),
                "reasoning": result.get("reasoning"),
                "session_id": req.session_id,
            }
        )
    except Exception as e:
        return error(500, str(e))


@router.post("/recommend")
async def recommend_products(req: RecommendRequest, db: AsyncSession = Depends(get_db)):
    """纯产品推荐接口"""
    agent = RecommendationAgent(db)
    result = await agent.execute(
        "推荐产品",
        customer_id=req.customer_id,
        top_n=req.top_n,
    )
    return success(data=result)


@router.post("/allocation")
async def asset_allocation(req: AllocationRequest, db: AsyncSession = Depends(get_db)):
    """资产配置建议接口"""
    agent = RecommendationAgent(db)
    result = await agent.execute("资产配置", customer_id=req.customer_id)
    return success(data=result)
