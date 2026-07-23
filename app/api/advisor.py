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
from app.utils.sse import stream_chat_result
from app.config.settings import get_settings
from app.security.authorization import enforce_customer_scope, require_roles
from sse_starlette.sse import EventSourceResponse

logger = get_logger(__name__)
router = APIRouter()
_settings = get_settings()


@router.post("/advisor")
async def advisor_chat(
    req: AdvisorChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
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

    enforce_customer_scope(user, req.customer_id)

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


@router.post("/advisor/stream")
async def advisor_chat_stream(
    req: AdvisorChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """SSE 投顾对话，保留原 JSON 接口用于兼容。"""
    if not req.customer_id:
        return error(400, "缺少 customer_id 参数")
    enforce_customer_scope(user, req.customer_id)
    agent = AdvisorAgent(db, req.session_id)
    result = await agent.execute(req.message, customer_id=req.customer_id)
    payload = {
        "reply": result.get("reply", "处理完成"),
        "sources": result.get("sources", []),
        "recommendations": result.get("recommendations", []),
        "customer_profile": result.get("customer_profile"),
        "reasoning": result.get("reasoning"),
        "session_id": req.session_id,
        "agent_type": "advisor",
    }
    return EventSourceResponse(
        stream_chat_result(payload, chunk_size=_settings.sse.chunk_size)
    )


@router.post("/recommend")
async def recommend_products(
    req: RecommendRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """纯产品推荐接口（直接调用 Agent，不走会话）"""
    enforce_customer_scope(user, req.customer_id)
    agent = AdvisorAgent(db)
    result = await agent.execute("推荐产品", customer_id=req.customer_id)
    return success(data=result)


@router.post("/allocation")
async def asset_allocation(
    req: AllocationRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles("客户", "理财顾问", "管理员")),
):
    """资产配置建议接口（直接调用 Agent，不走会话）"""
    enforce_customer_scope(user, req.customer_id)
    agent = AdvisorAgent(db)
    result = await agent.execute("资产配置", customer_id=req.customer_id)
    return success(data=result)
