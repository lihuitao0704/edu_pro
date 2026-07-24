import uuid
from typing import Any

from app.common_services.context_manager.entity_tracker import EntityTracker
from app.common_services.context_manager.memory_manager import MemoryManager
from app.common_services.context_manager.models import AgentResult
from app.common_services.orchestration.response_enhancer import ResponseEnhancer
from app.common_services.safety_guard.input_filter import InputSafetyFilter
from app.common_services.safety_guard.output_filter import OutputSafetyFilter
from app.common_services.trace_service.trace_service import TraceService
from app.model.schemas import UnifiedChatResponse


class ChatOrchestrator:
    """Shared execution pipeline around the existing Router Agent.

    The router and business agents remain domain adapters. Cross-cutting
    behavior is intentionally enforced here so future agents inherit it.
    """

    def __init__(
        self,
        router: Any,
        db=None,
        memory_manager: MemoryManager | None = None,
        entity_tracker: EntityTracker | None = None,
        input_filter: InputSafetyFilter | None = None,
        output_filter: OutputSafetyFilter | None = None,
        enhancer: ResponseEnhancer | None = None,
        trace_service: TraceService | None = None,
    ):
        self.router = router
        self.memory_manager = memory_manager or MemoryManager(db=db)
        self.entity_tracker = entity_tracker or EntityTracker()
        self.input_filter = input_filter or InputSafetyFilter()
        self.output_filter = output_filter or OutputSafetyFilter()
        self.enhancer = enhancer or ResponseEnhancer()
        self.trace_service = trace_service or TraceService()

    async def handle(
        self, message: str, session_id: str, actor_id: int, actor_role: str
    ) -> UnifiedChatResponse:
        session_id = session_id or uuid.uuid4().hex
        trace_id = uuid.uuid4().hex
        input_decision = self.input_filter.inspect(message)
        trace = self.trace_service.start(
            trace_id, session_id, actor_id, input_decision.sanitized_text
        )
        if input_decision.blocked:
            trace.finish("blocked", input_decision.user_message)
            return UnifiedChatResponse(
                intent="safety_block",
                agent="safety_guard",
                confidence=1.0,
                session_id=session_id,
                reply=input_decision.user_message,
                data={"trace_id": trace_id, "safety_flags": input_decision.matched_rules},
            )

        previous_context = await self.memory_manager.load_context(session_id, actor_id)
        entities = self.entity_tracker.track(
            input_decision.sanitized_text, previous_context.get("entities", {})
        )
        routed = await self.router.route(
            message=input_decision.sanitized_text,
            session_id=session_id,
            user_id=actor_id,
            user_role=actor_role,
            context={"entities": {**previous_context.get("entities", {}), **entities}},
        )
        trace.add_span("router_agent")
        trace.add_span(routed.agent)
        agent_result = AgentResult(
            reply=routed.reply,
            intent=routed.intent,
            agent_name=routed.agent,
            confidence=routed.confidence,
            data=routed.data if isinstance(routed.data, dict) else None,
            source_count=len((routed.data or {}).get("sources", [])) if isinstance(routed.data, dict) else 0,
            fallback_used=bool(isinstance(routed.data, dict) and routed.data.get("fallback_used")),
        )
        agent_result = self.enhancer.enhance(agent_result)
        output_decision = self.output_filter.inspect(agent_result.reply)
        agent_result.reply = output_decision.safe_reply
        context = self.memory_manager.save_context(
            session_id,
            actor_id,
            entities,
            last_intent=agent_result.intent,
            last_agent=agent_result.agent_name,
        )
        trace.finish("ok" if output_decision.allowed else "sanitized", agent_result.reply)
        data = dict(agent_result.data or {})
        data.update({
            "trace_id": trace_id,
            "context": context,
            "suggested_questions": agent_result.suggested_questions,
            "safety_flags": output_decision.matched_rules,
            "trace": {"total_latency_ms": trace.total_latency_ms, "spans": trace.spans},
        })
        return UnifiedChatResponse(
            intent=agent_result.intent,
            agent=agent_result.agent_name,
            confidence=agent_result.confidence,
            session_id=session_id,
            reply=agent_result.reply,
            data=data,
        )
