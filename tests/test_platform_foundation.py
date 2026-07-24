import unittest


class EntityTrackerTests(unittest.IsolatedAsyncioTestCase):
    def test_pronoun_resolves_latest_product_entity(self):
        from app.common_services.context_manager.entity_tracker import EntityTracker

        entity = EntityTracker().track(
            "它的风险等级是多少？",
            {"product_name": "稳健增长混合A"},
        )

        self.assertEqual("稳健增长混合A", entity["product_name"])
        self.assertEqual("session", entity["product_source"])

    def test_session_context_keeps_entities_for_the_next_turn(self):
        from app.common_services.context_manager.session_context import SessionContextStore

        store = SessionContextStore()
        store.update("session-1", 7, {"product_name": "稳健增长混合A"})

        context = store.get("session-1", 7)

        self.assertEqual("稳健增长混合A", context["entities"]["product_name"])

    def test_session_context_does_not_return_another_users_entities(self):
        from app.common_services.context_manager.session_context import SessionContextStore

        store = SessionContextStore()
        store.update("session-2", 7, {"product_name": "稳健增长混合A"})

        self.assertEqual({}, store.get("session-2", 8))

    async def test_memory_manager_restores_persisted_context_for_session_owner(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.common_services.context_manager.memory_manager import MemoryManager

        db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
            user_id=7, context_json={"entities": {"product_name": "稳健增长混合A"}}
        )))
        context = await MemoryManager(db=db).load_context("session-db", 7)

        self.assertEqual("稳健增长混合A", context["entities"]["product_name"])


class SafetyGuardTests(unittest.TestCase):
    def test_password_is_blocked_before_agent_execution(self):
        from app.common_services.safety_guard.input_filter import InputSafetyFilter

        decision = InputSafetyFilter().inspect("我的登录密码是 Passw0rd!123")

        self.assertTrue(decision.blocked)
        self.assertIn("隐私", decision.user_message)

    def test_phone_number_is_masked_without_blocking_question(self):
        from app.common_services.safety_guard.input_filter import InputSafetyFilter

        decision = InputSafetyFilter().inspect("请联系我的手机号13800138000咨询产品")

        self.assertFalse(decision.blocked)
        self.assertNotIn("13800138000", decision.sanitized_text)
        self.assertIn("138****8000", decision.sanitized_text)

    def test_guaranteed_return_is_rewritten_by_output_filter(self):
        from app.common_services.safety_guard.output_filter import OutputSafetyFilter

        decision = OutputSafetyFilter().inspect("该产品保证收益，稳赚不赔。")

        self.assertFalse(decision.allowed)
        self.assertIn("不承诺保本或收益", decision.safe_reply)


class ResponseEnhancementTests(unittest.TestCase):
    def test_low_confidence_investment_response_gets_guidance(self):
        from app.common_services.context_manager.models import AgentResult
        from app.common_services.orchestration.response_enhancer import ResponseEnhancer

        result = ResponseEnhancer().enhance(
            AgentResult(
                reply="可以为您介绍理财产品。",
                intent="investment_recommendation",
                agent_name="advisor",
                confidence=0.4,
            )
        )

        self.assertIn("投资期限", result.reply)
        self.assertGreaterEqual(len(result.suggested_questions), 3)


class TraceTests(unittest.TestCase):
    def test_trace_keeps_masked_input_only(self):
        from app.common_services.trace_service.trace_service import TraceService

        trace = TraceService().start(
            trace_id="trace-1", session_id="session-1", user_id=7,
            masked_input="手机号138****8000",
        )
        trace.finish("ok", "回答")

        record = TraceService().get("trace-1")
        self.assertEqual("手机号138****8000", record.masked_input)
        self.assertEqual("ok", record.status)


class PlatformPersistenceModelTests(unittest.TestCase):
    def test_platform_tables_have_stable_names(self):
        from app.model.entities import (
            FinAgentTrace, FinChatEntity, FinChatFeedback,
            FinChatMessage, FinChatSession,
        )

        self.assertEqual("fin_chat_session", FinChatSession.__tablename__)
        self.assertEqual("fin_chat_message", FinChatMessage.__tablename__)
        self.assertEqual("fin_chat_entity", FinChatEntity.__tablename__)
        self.assertEqual("fin_chat_feedback", FinChatFeedback.__tablename__)
        self.assertEqual("fin_agent_trace", FinAgentTrace.__tablename__)


if __name__ == "__main__":
    unittest.main()
