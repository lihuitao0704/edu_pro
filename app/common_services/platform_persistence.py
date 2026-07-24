from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import uuid

from app.model.entities import (
    FinAgentTrace, FinAgentTraceSpan, FinChatEntity, FinChatMessage, FinChatMetricDaily, FinChatSession,
)
from app.model.schemas import UnifiedChatResponse


class PlatformPersistenceService:
    """Durable platform records written once at the unified boundary."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def persist_turn(
        self, actor_id: int, user_content: str, response: UnifiedChatResponse
    ) -> None:
        try:
            session = await self.db.get(FinChatSession, response.session_id)
            data = response.data or {}
            context = data.get("context", {})
            if session is None:
                session = FinChatSession(
                    session_id=response.session_id,
                    user_id=actor_id,
                    last_intent=response.intent,
                    last_agent=response.agent,
                    context_json=context,
                )
                self.db.add(session)
            elif session.user_id != actor_id:
                raise PermissionError("session owner mismatch")
            else:
                session.last_intent = response.intent
                session.last_agent = response.agent
                session.context_json = context
                session.update_time = datetime.now()

            trace_id = data.get("trace_id")
            self.db.add(FinChatMessage(
                session_id=response.session_id, user_id=actor_id, role="user",
                content=user_content, intent=response.intent, agent_name=response.agent,
                trace_id=trace_id,
            ))
            self.db.add(FinChatMessage(
                session_id=response.session_id, user_id=actor_id, role="assistant",
                content=response.reply, intent=response.intent, agent_name=response.agent,
                trace_id=trace_id,
            ))
            for key, value in context.get("entities", {}).items():
                if key.endswith("_source") or not isinstance(value, str):
                    continue
                self.db.add(FinChatEntity(
                    session_id=response.session_id,
                    entity_type=key.removesuffix("_name"),
                    entity_key=key,
                    entity_name=value,
                    attributes_json={"source": context["entities"].get(f"{key}_source")},
                ))
            if trace_id:
                trace_meta = data.get("trace", {})
                self.db.add(FinAgentTrace(
                    trace_id=trace_id, session_id=response.session_id, user_id=actor_id,
                    intent=response.intent, target_agent=response.agent,
                    status="blocked" if response.agent == "safety_guard" else "ok",
                    input_masked=user_content, output_masked=response.reply,
                    total_latency_ms=trace_meta.get("total_latency_ms"),
                ))
                for span in trace_meta.get("spans", []):
                    self.db.add(FinAgentTraceSpan(
                        span_id=uuid.uuid4().hex, trace_id=trace_id,
                        span_type="agent", component_name=span["component_name"],
                        status=span["status"], latency_ms=span.get("latency_ms"),
                        token_input=span.get("token_input"), token_output=span.get("token_output"),
                    ))
            if hasattr(self.db, "execute"):
                metric = (await self.db.execute(
                    select(FinChatMetricDaily).where(
                        FinChatMetricDaily.metric_date == date.today(),
                        FinChatMetricDaily.intent == response.intent,
                        FinChatMetricDaily.agent_name == response.agent,
                    )
                )).scalar_one_or_none()
                if metric is None:
                    self.db.add(FinChatMetricDaily(
                        metric_date=date.today(), intent=response.intent,
                        agent_name=response.agent, session_count=1 if session.create_time == session.update_time else 0,
                        turn_count=1,
                    ))
                else:
                    metric.turn_count += 1
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
