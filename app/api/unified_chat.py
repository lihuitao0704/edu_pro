"""
统一对话入口 API — POST /api/chat

所有用户请求必须经过此入口：
  User Request → Router Agent → 意图分类 → Agent分发 → 统一响应

禁止前端直接调用业务 Agent。
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config.database import get_db
from app.model.schemas import UnifiedChatRequest, UnifiedChatResponse
from app.agent.router_agent import RouterAgent
from app.utils.response import success, error
from app.utils.sse import stream_chat_result
from app.utils.logger import get_logger
from app.security.authorization import (
    authenticated_actor_id,
    require_roles,
)
from app.config.settings import get_settings

logger = get_logger(__name__)
router = APIRouter()
_settings = get_settings()


@router.post("/chat", response_model=dict)
async def unified_chat(
    req: UnifiedChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(
        require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")
    ),
):
    """
    统一对话入口

    接收用户自然语言消息 → Router Agent 分类 → 分发至对应业务 Agent → 返回结果。

    支持的全部意图：
    - product_faq          → 客服 Agent（含闲聊自动转客服）
    - investment_recommend → 投顾 Agent
    - risk_control         → 风控 Agent
    - data_analysis        → 数据分析 Agent
    - business_operation   → 业务操作 Agent
    - chitchat             → 客服 Agent
    """
    try:
        agent = RouterAgent(db)
        result = await agent.route(
            message=req.message,
            session_id=req.session_id,
            user_id=authenticated_actor_id(user),
            user_role=get_request_role_from_user(user),
        )
        logger.info(
            f"统一入口响应 | intent={result.intent} | agent={result.agent} "
            f"| session={result.session_id}"
        )
        return success(data=result.model_dump())
    except Exception as e:
        logger.error(f"统一入口异常: {e}", exc_info=True)
        return error(500, f"服务异常: {str(e)}")


@router.post("/chat/stream")
async def unified_chat_stream(
    req: UnifiedChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(
        require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")
    ),
):
    """
    统一对话入口（SSE 流式）

    所有意图均支持 SSE 流式输出：
      event: meta  → {intent, agent, session_id, confidence}
      event: delta → {content: "..."}
      event: done  → {session_id}

    对于非自然流式 Agent（如 business_operation），完整回复作为单个 delta 输出。
    """
    try:
        agent = RouterAgent(db)
        result = await agent.route(
            message=req.message,
            session_id=req.session_id,
            user_id=authenticated_actor_id(user),
            user_role=get_request_role_from_user(user),
        )
        payload = result.model_dump()
        # 补充 agent_type 供 SSE meta 事件使用
        payload["agent_type"] = result.agent
        return EventSourceResponse(
            stream_chat_result(payload, chunk_size=_settings.sse.chunk_size)
        )
    except Exception as e:
        logger.error(f"统一入口SSE异常: {e}", exc_info=True)
        # SSE 异常也尝试以流式返回错误
        async def error_stream():
            import json
            yield {"event": "meta", "data": json.dumps({"error": str(e)})}
            yield {"event": "delta", "data": json.dumps({"content": f"服务异常: {str(e)}"})}
            yield {"event": "done", "data": json.dumps({"session_id": req.session_id})}
        return EventSourceResponse(error_stream())


def get_request_role_from_user(user: dict) -> str:
    """Use the authenticated role, never a client-claimed chat role."""
    return str(user.get("role") or "")
