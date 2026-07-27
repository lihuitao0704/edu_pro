"""
统一对话入口 API — POST /api/chat

所有用户请求必须经过此入口：
  User Request → Router Agent → 意图分类 → Agent分发 → 统一响应

禁止前端直接调用业务 Agent。
"""

from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config.database import get_db
from app.model.entities import ConversationArchive, FinChatFeedback, FinChatSession
from app.model.route_decision import RouteDecision
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
from app.common_services.context_manager.memory_manager import MemoryManager
from app.common_services.safety_guard.input_filter import InputSafetyFilter
from app.common_services.platform_persistence import PlatformPersistenceService

logger = get_logger(__name__)
router = APIRouter()
_settings = get_settings()


async def resolve_owned_session_id(db: AsyncSession, session_id: str, actor_id: int) -> str:
    """Reuse only a persisted session owned by the JWT actor.

    A client-provided, unknown id is discarded so it cannot select an old
    short-term-memory key. The router creates a new opaque id for fresh chats.

    运营商确认流程依赖此机制:
      第一次请求: session_id="" → 生成新 UUID → persist_turn 持久化到 DB → 返回前端
      第二次请求: session_id=UUID → DB 找到 → 所有权校验通过 → 同一 session_id → Redis pending 命中
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
        session_id = (
            await resolve_owned_session_id(db, req.session_id, actor_id)
            or uuid.uuid4().hex
        )
        orchestrator = ChatOrchestrator(router=RouterAgent(db), db=db)
        result = await orchestrator.handle(
            req.message,
            session_id,
            actor_id,
            get_request_role_from_user(user),
            customer_id=get_subject_customer_id(user, req.user_id),
        )
        safe_input = InputSafetyFilter().inspect(req.message).sanitized_text
        try:
            if result.agent != "safety_guard":
                await MemoryService(db).archive_turn(
                    result.session_id, actor_id, result.agent, safe_input, result.reply
                )
            await PlatformPersistenceService(db).persist_turn(actor_id, safe_input, result)
        except Exception as e:
            logger.warning(f"对话归档失败(不影响响应): {e}")
        logger.info(
            f"统一入口响应 | intent={result.intent} | agent={result.agent} "
            f"| session={result.session_id}"
        )
        return success(data=result.model_dump())
    except Exception as e:
        logger.error(f"统一入口异常: {e}", exc_info=True)
        return error(500, "服务暂时不可用，请稍后重试。")


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
        session_id = (
            await resolve_owned_session_id(db, req.session_id, actor_id)
            or uuid.uuid4().hex
        )
        orchestrator = ChatOrchestrator(router=RouterAgent(db), db=db)
        result = await orchestrator.handle(
            req.message,
            session_id,
            actor_id,
            get_request_role_from_user(user),
            customer_id=get_subject_customer_id(user, req.user_id),
        )
        safe_input = InputSafetyFilter().inspect(req.message).sanitized_text
        try:
            if result.agent != "safety_guard":
                await MemoryService(db).archive_turn(
                    result.session_id, actor_id, result.agent, safe_input, result.reply
                )
            await PlatformPersistenceService(db).persist_turn(actor_id, safe_input, result)
        except Exception as e:
            logger.warning(f"对话归档失败(不影响响应): {e}")
        payload = result.model_dump()
        payload["agent_type"] = result.agent
        return EventSourceResponse(
            stream_chat_result(payload, chunk_size=_settings.sse.chunk_size)
        )
    except Exception as e:
        logger.error(f"统一入口SSE异常: {e}", exc_info=True)
        # SSE 异常也尝试以流式返回错误
        async def error_stream():
            import json
            yield {"event": "meta", "data": json.dumps({"error": "service_unavailable"})}
            yield {"event": "delta", "data": json.dumps({"content": "服务暂时不可用，请稍后重试。"})}
            yield {"event": "done", "data": json.dumps({"session_id": session_id})}
        return EventSourceResponse(error_stream())


@router.post("/chat/stream/v2")
async def unified_chat_stream_v2(
    req: UnifiedChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(
        require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")
    ),
):
    """
    统一对话入口 SSE 真流式 v2

    投顾意图走 AdvisorAgent.stream_execute() — LLM token 级实时流式。
    其他意图回退到 ChatOrchestrator 阻塞后分块流式。

    事件契约:
      event: meta     → {agent, session_id}
      event: token    → {content: "为"}          # LLM 逐 token
      event: tool_end → {name: "smart_recommend"}
      event: done     → {reply, recommendations, allocation, session_id}
      event: error    → {message}
    """
    import json
    actor_id = authenticated_actor_id(user)
    session_id = (
        await resolve_owned_session_id(db, req.session_id, actor_id)
        or uuid.uuid4().hex
    )

    # ── 先执行输入安全过滤，再生成一次可复用的顶层路由决策 ──
    input_decision = InputSafetyFilter().inspect(req.message)
    routing_message = input_decision.sanitized_text
    if input_decision.blocked:
        # ChatOrchestrator owns the standard safety-block response.
        route_decision = None
        route_plan = None
        intent = "safety_block"
        confidence = 1.0
    else:
        try:
            from app.service.intent_service import get_intent_service
            from app.service.route_validator import get_route_validator

            intent_svc = get_intent_service()
            actor_role = get_request_role_from_user(user)
            route_context = await MemoryManager(db=db).load_context(
                session_id, actor_id
            )
            route_plan = await intent_svc.plan_route(
                routing_message,
                user_role=actor_role,
                context=route_context,
            )
            route_plan.tasks = [
                get_route_validator().validate(
                    decision,
                    user_role=actor_role,
                    context=route_context,
                )
                for decision in route_plan.tasks
            ]
            route_decision = (
                route_plan.tasks[0] if not route_plan.is_multi_intent else None
            )
            if (
                route_decision is not None
                and route_decision.intent == "investment_recommendation"
                and actor_role == "客户"
            ):
                route_decision.entities["customer_id"] = actor_id
            intent = (
                "multi_intent"
                if route_plan.is_multi_intent
                else route_decision.intent
            )
            confidence = min(
                (decision.confidence for decision in route_plan.tasks),
                default=0.0,
            )
        except Exception as exc:
            logger.warning("流式入口路由预判失败，交由编排层澄清: %s", exc)
            route_decision = None
            route_plan = None
            intent = "clarification"
            confidence = 0.0

    # ── 投顾意图 → 真流式 ──
    if intent == "investment_recommendation":
        safe_input = routing_message
        subject_customer_id, subject_resolution_reply = (
            await resolve_stream_advisor_subject(
                user,
                req.user_id,
                route_decision,
            )
        )
        if subject_customer_id is not None and route_decision is not None:
            route_decision.entities["customer_id"] = subject_customer_id

        async def advisor_event_stream():
            if subject_resolution_reply:
                yield {
                    "event": "meta",
                    "data": json.dumps(
                        {
                            "agent": "advisor",
                            "session_id": session_id,
                            "confidence": confidence,
                        },
                        ensure_ascii=False,
                    ),
                }
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "reply": subject_resolution_reply,
                            "recommendations": [],
                            "customer_profile": None,
                            "status": "customer_resolution_required",
                            "session_id": session_id,
                            "route_decision": (
                                route_decision.model_dump(mode="json")
                                if route_decision is not None
                                else None
                            ),
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                }
                return

            from app.agent.advisor_agent import AdvisorAgent
            agent = AdvisorAgent(db, session_id, actor_id=actor_id)
            final_payload: dict = {}
            try:
                async for evt in agent.stream_execute(
                    safe_input,
                    customer_id=subject_customer_id,
                    audience_role=get_request_role_from_user(user),
                ):
                    # 过滤掉 py 对象，确保 JSON 可序列化
                    event_payload = dict(evt)
                    evt_type = event_payload.pop("type", "message")
                    safe = _make_json_safe(event_payload)
                    if evt_type == "done":
                        safe["route_decision"] = route_decision.model_dump(
                            mode="json"
                        )
                        final_payload = safe
                    yield {
                        "event": evt_type,
                        "data": json.dumps(safe, ensure_ascii=False, default=str),
                    }
            except Exception as e:
                logger.error(f"投顾流式异常: {e}", exc_info=True)
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"message": "当前智能投顾服务繁忙，请稍后重试。"},
                        ensure_ascii=False,
                    ),
                }

            # 流结束后按真实账户归档完整轮次，并写入会话所有权记录。
            try:
                final_reply = str(final_payload.get("reply") or "")
                remembered_entities = dict(
                    route_decision.entities if route_decision is not None else {}
                )
                if subject_customer_id is not None:
                    remembered_entities["customer_id"] = subject_customer_id
                recommendations = final_payload.get("recommendations")
                if isinstance(recommendations, list) and recommendations:
                    first = recommendations[0]
                    if isinstance(first, dict):
                        product_name = (
                            first.get("product_name")
                            or first.get("name")
                        )
                        product_id = first.get("product_id") or first.get("id")
                        if product_name:
                            remembered_entities["product_name"] = product_name
                        if product_id:
                            remembered_entities["product_id"] = product_id
                await MemoryManager(db=db).save_context(
                    session_id,
                    actor_id,
                    remembered_entities,
                    last_intent="investment_recommendation",
                    last_agent="advisor",
                    pending_route_decision=None,
                )
                await MemoryService(db).archive_turn(
                    session_id, actor_id, "advisor", safe_input, final_reply
                )
                persisted = UnifiedChatResponse(
                    intent="investment_recommendation",
                    agent="advisor",
                    confidence=float(confidence or 0),
                    session_id=session_id,
                    reply=final_reply,
                    data=final_payload,
                )
                await PlatformPersistenceService(db).persist_turn(
                    actor_id, safe_input, persisted
                )
            except Exception as exc:
                logger.warning("投顾流式归档失败: %s", exc)

        return EventSourceResponse(advisor_event_stream())

    # ── 非投顾意图 → 回退到旧流式（ChatOrchestrator 阻塞后分块）──
    try:
        orchestrator = ChatOrchestrator(router=RouterAgent(db), db=db)
        result = await orchestrator.handle(
            req.message, session_id, actor_id,
            get_request_role_from_user(user),
            customer_id=get_subject_customer_id(user, req.user_id),
            route_decision=route_decision,
            route_plan=route_plan,
        )
        safe_input = InputSafetyFilter().inspect(req.message).sanitized_text
        if result.agent != "safety_guard":
            await MemoryService(db).archive_turn(
                result.session_id, actor_id, result.agent, safe_input, result.reply
            )
        await PlatformPersistenceService(db).persist_turn(actor_id, safe_input, result)
        payload = result.model_dump()
        payload["agent_type"] = result.agent
        return EventSourceResponse(
            stream_chat_result(payload, chunk_size=_settings.sse.chunk_size)
        )
    except Exception as e:
        logger.error(f"统一入口SSE v2异常: {e}", exc_info=True)
        async def error_stream():
            yield {"event": "meta", "data": json.dumps({"error": "service_unavailable"})}
            yield {"event": "delta", "data": json.dumps({"content": "服务暂时不可用，请稍后重试。"})}
            yield {"event": "done", "data": json.dumps({"session_id": session_id})}
        return EventSourceResponse(error_stream())


def _make_json_safe(obj: dict) -> dict:
    """递归清理 dict，将 Pydantic 模型转为普通 dict"""
    result = {}
    for k, v in obj.items():
        if hasattr(v, "model_dump"):
            result[k] = v.model_dump()
        elif isinstance(v, dict):
            result[k] = _make_json_safe(v)
        elif isinstance(v, list):
            result[k] = [
                x.model_dump() if hasattr(x, "model_dump") else x for x in v
            ]
        else:
            result[k] = v
    return result


@router.post("/chat/recommend")
async def chat_recommend(
    req: UnifiedChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(
        require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员")
    ),
):
    """
    直调投顾 Agent 推荐 — 不走编排器，无对话归档。

    轻量端点，专供顾问工作台「生成推荐方案」按钮使用。
    直调 AdvisorAgent，无编排器开销，无对话归档。
    """
    from app.agent.advisor_agent import AdvisorAgent
    actor_id = authenticated_actor_id(user)
    session_id = (
        await resolve_owned_session_id(db, req.session_id, actor_id)
        or uuid.uuid4().hex
    )
    agent = AdvisorAgent(db, session_id, actor_id=actor_id)
    result = await agent.execute(
        req.message,
        customer_id=get_subject_customer_id(user, req.user_id),
        audience_role=get_request_role_from_user(user),
    )
    return success(data={
        "reply": result.get("reply", ""),
        "recommendations": result.get("recommendations", []),
        "allocation": result.get("allocation"),
        "customer_profile": result.get("customer_profile"),
        "reasoning": result.get("reasoning"),
    })


def get_request_role_from_user(user: dict) -> str:
    """Use the authenticated role, never a client-claimed chat role."""
    return str(user.get("role") or "")


def get_subject_customer_id(user: dict, claimed_user_id: int) -> int | None:
    """Separate the authenticated actor from the customer being discussed.

    Customer accounts are always scoped to themselves. Employee roles may
    explicitly select a customer through the request payload.
    """
    actor_id = authenticated_actor_id(user)
    if get_request_role_from_user(user) == "客户":
        return actor_id
    target_id = int(claimed_user_id or 0)
    return target_id or None


async def resolve_stream_advisor_subject(
    user: dict,
    claimed_user_id: int,
    route_decision: RouteDecision | None,
) -> tuple[int | None, str | None]:
    """Resolve an advisor target without confusing the actor with a customer."""
    role = get_request_role_from_user(user)
    entities = (
        route_decision.entities
        if route_decision is not None
        and isinstance(route_decision.entities, dict)
        else {}
    )

    if role == "客户":
        # 隐私保护：客户身份不能查询他人信息
        actor_id = authenticated_actor_id(user)
        customer_name = str(entities.get("customer_name") or "").strip()
        explicit_customer_id = entities.get("customer_id")
        if customer_name:
            from app.tool.graph_query_tool import resolve_customer_id
            resolved = await resolve_customer_id(customer_name)
            if resolved is not None and int(resolved) != actor_id:
                return (
                    None,
                    (
                        '抱歉，为了保护客户隐私，'
                        '我只能协助您查询本人账户相关信息。'
                        '您可以试试：'
                        '"查看我的风险等级"'
                        '"查询我的持仓"'
                        '或"查询我的交易记录"。'
                    ),
                )
        if explicit_customer_id is not None:
            try:
                if int(explicit_customer_id) != actor_id:
                    return (
                        None,
                        (
                            '抱歉，为了保护客户隐私，'
                            '我只能协助您查询本人账户相关信息。'
                            '您可以试试：'
                            '"查看我的风险等级"'
                            '"查询我的持仓"'
                            '或"查询我的交易记录"。'
                        ),
                    )
            except (TypeError, ValueError):
                return None, "客户ID格式无效，请提供有效的数字客户ID。"
        return actor_id, None

    # 员工角色：通过姓名或 ID 解析目标客户
    customer_name = str(entities.get("customer_name") or "").strip()
    if customer_name:
        from app.tool.graph_query_tool import resolve_customer_id

        resolved_customer_id = await resolve_customer_id(customer_name)
        if resolved_customer_id is None:
            return (
                None,
                f"没有找到唯一匹配的客户“{customer_name}”。"
                "请核对姓名，或直接提供客户ID后再试。",
            )
        return int(resolved_customer_id), None

    explicit_customer_id = entities.get("customer_id")
    if explicit_customer_id is not None:
        try:
            return int(explicit_customer_id), None
        except (TypeError, ValueError):
            return None, "客户ID格式无效，请提供有效的数字客户ID。"

    # Kept for request-schema compatibility. An employee's login id is actor
    # identity and must never silently become the recommendation subject.
    del claimed_user_id
    return None, None


def get_stream_subject_customer_id(
    user: dict,
    claimed_user_id: int,
    route_decision: RouteDecision | None,
) -> int | None:
    """Select only a trusted customer id for the streaming advisor."""
    if get_request_role_from_user(user) == "客户":
        return authenticated_actor_id(user)
    explicit_customer_id = (
        route_decision.entities.get("customer_id")
        if route_decision is not None
        and isinstance(route_decision.entities, dict)
        else None
    )
    del claimed_user_id
    return int(explicit_customer_id) if explicit_customer_id is not None else None
