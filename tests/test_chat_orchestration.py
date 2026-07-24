import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock


class ChatOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_unified_endpoint_uses_shared_orchestrator(self):
        from app.api.unified_chat import unified_chat
        from app.model.schemas import UnifiedChatRequest, UnifiedChatResponse
        from unittest.mock import patch

        response = UnifiedChatResponse(
            intent="product_faq", agent="customer_service", confidence=0.9,
            session_id="s-api", reply="ok", data={},
        )
        orchestrator = SimpleNamespace(handle=AsyncMock(return_value=response))
        memory_service = SimpleNamespace(archive_turn=AsyncMock())
        platform_persistence = SimpleNamespace(persist_turn=AsyncMock())
        request = UnifiedChatRequest(message="产品问题", session_id="s-api")

        with patch("app.api.unified_chat.ChatOrchestrator", return_value=orchestrator), \
             patch("app.api.unified_chat.MemoryService", return_value=memory_service), \
             patch("app.api.unified_chat.PlatformPersistenceService", return_value=platform_persistence), \
             patch("app.api.unified_chat.resolve_owned_session_id", new=AsyncMock(return_value="s-api")):
            result = await unified_chat(request, AsyncMock(), {"user_id": 7, "role": "客户"})

        orchestrator.handle.assert_awaited_once_with("产品问题", "s-api", 7, "客户")
        memory_service.archive_turn.assert_awaited_once_with(
            "s-api", 7, "customer_service", "产品问题", "ok"
        )
        platform_persistence.persist_turn.assert_awaited_once_with(7, "产品问题", response)
        self.assertEqual("ok", result["data"]["reply"])

    async def test_unified_endpoint_does_not_archive_blocked_input(self):
        from app.api.unified_chat import unified_chat
        from app.model.schemas import UnifiedChatRequest, UnifiedChatResponse
        from unittest.mock import patch

        response = UnifiedChatResponse(
            intent="safety_block", agent="safety_guard", confidence=1.0,
            session_id="s-block", reply="请不要输入密码", data={},
        )
        orchestrator = SimpleNamespace(handle=AsyncMock(return_value=response))
        memory_service = SimpleNamespace(archive_turn=AsyncMock())
        platform_persistence = SimpleNamespace(persist_turn=AsyncMock())

        with patch("app.api.unified_chat.ChatOrchestrator", return_value=orchestrator), \
             patch("app.api.unified_chat.MemoryService", return_value=memory_service), \
             patch("app.api.unified_chat.PlatformPersistenceService", return_value=platform_persistence), \
             patch("app.api.unified_chat.resolve_owned_session_id", new=AsyncMock(return_value="s-block")):
            await unified_chat(
                UnifiedChatRequest(message="密码是Secret123", session_id="s-block"),
                AsyncMock(), {"user_id": 7, "role": "客户"},
            )

        memory_service.archive_turn.assert_not_awaited()
        platform_persistence.persist_turn.assert_awaited_once_with(7, "", response)

    async def test_blocked_input_never_reaches_router(self):
        from app.common_services.orchestration.chat_orchestrator import ChatOrchestrator

        router = SimpleNamespace(route=AsyncMock())
        result = await ChatOrchestrator(router=router).handle(
            message="我的密码是 Secret123", session_id="s-1", actor_id=7, actor_role="客户"
        )

        router.route.assert_not_awaited()
        self.assertEqual("safety_guard", result.agent)
        self.assertIn("隐私", result.reply)

    async def test_orchestrator_passes_masked_input_and_persists_product_context(self):
        from app.common_services.orchestration.chat_orchestrator import ChatOrchestrator

        routed = SimpleNamespace(
            reply="可以为您介绍理财产品。",
            intent="investment_recommendation",
            agent="advisor",
            confidence=0.4,
            session_id="s-2",
            data=None,
        )
        router = SimpleNamespace(route=AsyncMock(return_value=routed))
        orchestrator = ChatOrchestrator(router=router)

        result = await orchestrator.handle(
            message="查一下稳健增长混合A，联系电话13800138000",
            session_id="s-2", actor_id=7, actor_role="客户"
        )

        self.assertNotIn("13800138000", router.route.await_args.kwargs["message"])
        self.assertIn("投资期限", result.reply)
        self.assertEqual("稳健增长混合A", result.data["context"]["entities"]["product_name"])

    async def test_orchestrator_replaces_noncompliant_agent_reply(self):
        from app.common_services.orchestration.chat_orchestrator import ChatOrchestrator

        routed = SimpleNamespace(
            reply="该产品保证收益，稳赚不赔。",
            intent="product_faq",
            agent="customer_service",
            confidence=0.9,
            session_id="s-3",
            data=None,
        )
        router = SimpleNamespace(route=AsyncMock(return_value=routed))

        result = await ChatOrchestrator(router=router).handle(
            message="产品怎么样", session_id="s-3", actor_id=7, actor_role="客户"
        )

        self.assertIn("不承诺保本或收益", result.reply)
        self.assertIn("guaranteed_return", result.data["safety_flags"])


if __name__ == "__main__":
    unittest.main()
