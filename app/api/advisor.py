"""投顾对话 API 路由 — LLM Agent 统一驱动

决策者从「开发者的 if/elif」变为「LLM 大模型」。
API 层只做一件事：创建 AdvisorAgent → 调用 execute → 返回结果。
Agent 内部自行决定调用哪个工具、按什么顺序调用。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.agent.advisor_agent import AdvisorAgent
from app.model.schemas import AdvisorChatRequest, RecommendRequest, AllocationRequest
from app.utils.response import success, error
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/advisor")
async def advisor_chat(req: AdvisorChatRequest, db: AsyncSession = Depends(get_db)):
    """
    投顾对话接口（LLM Agent 驱动）

    接收用户自然语言消息 → 交给 AdvisorAgent → Agent 自行决策工具调用链 → 返回回复。

    Agent 工具箱：
      - profile_tool       → 查客户风险画像
      - recommend_products → 产品推荐打分
      - asset_allocation   → 资产配置建议
      - graphrag_search    → 知识图谱 + 文档检索
    """
    if not req.customer_id:
        return error(400, "缺少 customer_id 参数")

    try:
        agent = AdvisorAgent(db, req.session_id)
        result = await agent.execute(req.message, customer_id=req.customer_id)

        return success(data={
            "reply": result.get("reply", "处理完成"),
            "recommendations": result.get("recommendations", []),
            "customer_profile": result.get("customer_profile"),
            "reasoning": result.get("reasoning"),
            "session_id": req.session_id,
        })
    except Exception as e:
        logger.error(f"投顾对话异常: {e}", exc_info=True)
        return error(500, f"投顾服务异常: {str(e)}")


@router.post("/recommend")
async def recommend_products(req: RecommendRequest, db: AsyncSession = Depends(get_db)):
    """纯产品推荐接口（直接调用 Agent，不走会话）"""
    agent = AdvisorAgent(db)
    result = await agent.execute("推荐产品", customer_id=req.customer_id)
    return success(data=result)


@router.post("/allocation")
async def asset_allocation(req: AllocationRequest, db: AsyncSession = Depends(get_db)):
    """资产配置建议接口（直接调用 Agent，不走会话）"""
    agent = AdvisorAgent(db)
    result = await agent.execute("资产配置", customer_id=req.customer_id)
    return success(data=result)
