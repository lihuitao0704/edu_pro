"""
统一对话入口 API — POST /api/chat

所有用户请求必须经过此入口：
  User Request → Router Agent → 意图分类 → Agent分发 → 统一响应

禁止前端直接调用业务 Agent。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config.database import get_db
from app.model.entities import ConversationArchive, FinChatFeedback, FinChatSession
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
from sqlalchemy import select
from app.service.memory_service import MemoryService
from app.common_services.orchestration.chat_orchestrator import ChatOrchestrator
from app.common_services.safety_guard.input_filter import InputSafetyFilter
from app.common_services.platform_persistence import PlatformPersistenceService

logger = get_logger(__name__)
router = APIRouter()
_settings = get_settings()


async def resolve_owned_session_id(db: AsyncSession, session_id: str, actor_id: int) -> str:
    """Reuse only a persisted session owned by the JWT actor.

    A client-provided, unknown id is discarded so it cannot select an old
    short-term-memory key. The router creates a new opaque id for fresh chats.
    """
    if not session_id:
        return ""
    if hasattr(db, "get"):
        platform_session = await db.get(FinChatSession, session_id)
        if platform_session is not None:
            return session_id if int(platform_session.user_id) == actor_id else ""
    owner = (
        await db.execute(
            select(ConversationArchive.user_id)
            .where(ConversationArchive.session_id == session_id)
            .order_by(ConversationArchive.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if owner is not None and int(owner) == actor_id:
        return session_id
    logger.warning("rejected unknown or foreign chat session | actor=%s | session=%s", actor_id, session_id)
    return ""


@router.get("/chat/history", response_model=dict)
async def get_chat_history(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(
        require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")
    ),
    view: str = "messages",
    session_id: str = "",
    intent: str = "",
    agent_name: str = "",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
):
    """Return the most recent persisted conversation for the authenticated user."""
    actor_id = authenticated_actor_id(user)
    if view == "sessions" or any((session_id, intent, agent_name, start_time, end_time)):
        statement = select(FinChatSession).where(FinChatSession.user_id == actor_id)
        if session_id:
            statement = statement.where(FinChatSession.session_id == session_id)
        if intent:
            statement = statement.where(FinChatSession.last_intent == intent)
        if agent_name:
            statement = statement.where(FinChatSession.last_agent == agent_name)
        if start_time:
            statement = statement.where(FinChatSession.update_time >= start_time)
        if end_time:
            statement = statement.where(FinChatSession.update_time <= end_time)
        sessions = (await db.execute(
            statement.order_by(FinChatSession.update_time.desc()).limit(50)
        )).scalars().all()
        session_ids = [item.session_id for item in sessions]
        ratings = {}
        if session_ids:
            feedback = (await db.execute(
                select(FinChatFeedback)
                .where(FinChatFeedback.user_id == actor_id, FinChatFeedback.session_id.in_(session_ids))
                .order_by(FinChatFeedback.created_time.desc())
            )).scalars().all()
            for item in feedback:
                ratings.setdefault(item.session_id, item.rating)
        return success(data={"items": [
            {
                "session_id": item.session_id,
                "summary": item.summary or "",
                "intent": item.last_intent,
                "agents": [item.last_agent] if item.last_agent else [],
                "rating": ratings.get(item.session_id),
                "updated_time": item.update_time.isoformat() if item.update_time else None,
            }
            for item in sessions
        ]})
    records = (
        await db.execute(
            select(ConversationArchive)
            .where(ConversationArchive.user_id == actor_id)
            .order_by(ConversationArchive.create_time.desc(), ConversationArchive.id.desc())
            .limit(50)
        )
    ).scalars().all()
    if not records:
        return success(data={"session_id": "", "messages": []})

    session_id = records[0].session_id
    messages = [record for record in reversed(records) if record.session_id == session_id]
    return success(data={
        "session_id": session_id,
        "messages": [
            {
                "role": record.role,
                "content": record.content,
                "created_at": record.create_time.isoformat() if record.create_time else None,
            }
            for record in messages
        ],
    })


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
        actor_id = authenticated_actor_id(user)
        session_id = await resolve_owned_session_id(db, req.session_id, actor_id)
        orchestrator = ChatOrchestrator(router=RouterAgent(db), db=db)
        result = await orchestrator.handle(
            req.message, session_id, actor_id, get_request_role_from_user(user)
        )
        safe_input = InputSafetyFilter().inspect(req.message).sanitized_text
        if result.agent != "safety_guard":
            await MemoryService(db).archive_turn(
                result.session_id, actor_id, result.agent, safe_input, result.reply
            )
        await PlatformPersistenceService(db).persist_turn(actor_id, safe_input, result)
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
        actor_id = authenticated_actor_id(user)
        session_id = await resolve_owned_session_id(db, req.session_id, actor_id)
        orchestrator = ChatOrchestrator(router=RouterAgent(db), db=db)
        result = await orchestrator.handle(
            req.message, session_id, actor_id, get_request_role_from_user(user)
        )
        safe_input = InputSafetyFilter().inspect(req.message).sanitized_text
        if result.agent != "safety_guard":
            await MemoryService(db).archive_turn(
                result.session_id, actor_id, result.agent, safe_input, result.reply
            )
        await PlatformPersistenceService(db).persist_turn(actor_id, safe_input, result)
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
