import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch


class ChatHistoryContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_returns_only_latest_authenticated_users_session(self):
        from app.api.unified_chat import get_chat_history

        records = [
            SimpleNamespace(session_id="session-7", role="assistant", content="答复", create_time=datetime(2026, 7, 24, 9, 1)),
            SimpleNamespace(session_id="session-7", role="user", content="上一个问题", create_time=datetime(2026, 7, 24, 9)),
            SimpleNamespace(session_id="session-old", role="user", content="旧问题", create_time=datetime(2026, 7, 23, 9)),
        ]
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: records)
                )
            )
        )

        result = await get_chat_history(db=db, user={"user_id": 7, "role": "客户"})

        self.assertEqual("session-7", result["data"]["session_id"])
        self.assertEqual(["上一个问题", "答复"], [item["content"] for item in result["data"]["messages"]])


class CustomerContextContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_customer_investment_chat_uses_authenticated_customer_id(self):
        from app.agent.router_agent import RouterAgent

        router = RouterAgent(AsyncMock())
        router.intent_service.classify_router = AsyncMock(
            return_value=("investment_recommendation", 0.9, {})
        )
        router._dispatch_advisor = AsyncMock(return_value={"reply": "ok", "data": {}})

        await router.route("评估我的持仓", user_id=7, user_role="客户")

        self.assertEqual(7, router._dispatch_advisor.await_args.args[3])

    async def test_employee_investment_chat_does_not_use_employee_id_as_customer_id(self):
        from app.agent.router_agent import RouterAgent

        router = RouterAgent(AsyncMock())
        router.intent_service.classify_router = AsyncMock(
            return_value=("investment_recommendation", 0.9, {})
        )
        router._dispatch_advisor = AsyncMock(return_value={"reply": "ok", "data": {}})

        await router.route("评估客户持仓", user_id=99, user_role="理财顾问")

        self.assertIsNone(router._dispatch_advisor.await_args.args[3])


class ArchiveTurnContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_archive_turn_persists_user_and_assistant_before_returning(self):
        from app.service.memory_service import MemoryService

        db = SimpleNamespace(add=Mock(), commit=AsyncMock(), rollback=AsyncMock())

        await MemoryService(db).archive_turn("session-7", 7, "customer_service", "问题", "答复")

        self.assertEqual(2, db.add.call_count)
        db.commit.assert_awaited_once()

    async def test_archive_turn_propagates_a_persistence_failure(self):
        from app.service.memory_service import MemoryService

        db = SimpleNamespace(
            add=Mock(),
            commit=AsyncMock(side_effect=RuntimeError("database unavailable")),
            rollback=AsyncMock(),
        )

        with self.assertRaisesRegex(RuntimeError, "conversation turn archive failed"):
            await MemoryService(db).archive_turn("session-7", 7, "customer_service", "q", "a")

        db.rollback.assert_awaited_once()


class SessionOwnershipContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_session_id_is_not_reused(self):
        from app.api.unified_chat import resolve_owned_session_id

        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
            )
        )

        session_id = await resolve_owned_session_id(db, "client-supplied-session", 7)

        self.assertEqual("", session_id)

    async def test_foreign_session_id_is_not_reused(self):
        from app.api.unified_chat import resolve_owned_session_id

        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(scalar_one_or_none=lambda: 8)
            )
        )

        session_id = await resolve_owned_session_id(db, "session-owned-by-8", 7)

        self.assertEqual("", session_id)

    async def test_own_session_id_is_reused(self):
        from app.api.unified_chat import resolve_owned_session_id

        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(scalar_one_or_none=lambda: 7)
            )
        )

        session_id = await resolve_owned_session_id(db, "session-owned-by-7", 7)

        self.assertEqual("session-owned-by-7", session_id)


class UnifiedArchiveContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_unified_chat_archives_each_agent_turn_for_the_authenticated_actor(self):
        from app.api.unified_chat import unified_chat
        from app.model.schemas import UnifiedChatRequest

        request = UnifiedChatRequest(message="test", session_id="client-session")
        routed = SimpleNamespace(
            intent="business_operation",
            agent="operator",
            confidence=0.9,
            session_id="server-session",
            reply="done",
            data=None,
            model_dump=lambda: {},
        )
        route_agent = SimpleNamespace(route=AsyncMock(return_value=routed))
        memory_service = SimpleNamespace(archive_turn=AsyncMock())

        with patch("app.api.unified_chat.RouterAgent", return_value=route_agent), \
             patch("app.api.unified_chat.resolve_owned_session_id", new=AsyncMock(return_value="")), \
             patch("app.api.unified_chat.MemoryService", return_value=memory_service):
            await unified_chat(request, AsyncMock(), {"user_id": 7, "role": "customer"})

        memory_service.archive_turn.assert_awaited_once_with(
            "server-session", 7, "operator", "test", "done"
        )

    async def test_stream_rejects_foreign_session_and_archives_for_actor(self):
        from app.api.unified_chat import unified_chat_stream
        from app.model.schemas import UnifiedChatRequest

        request = UnifiedChatRequest(message="test", session_id="session-owned-by-8")
        routed = SimpleNamespace(
            intent="business_operation",
            agent="operator",
            confidence=0.9,
            session_id="fresh-server-session",
            reply="done",
            data=None,
            model_dump=lambda: {},
        )
        route_agent = SimpleNamespace(route=AsyncMock(return_value=routed))
        memory_service = SimpleNamespace(archive_turn=AsyncMock())
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(scalar_one_or_none=lambda: 8)
            )
        )

        with patch("app.api.unified_chat.RouterAgent", return_value=route_agent), \
             patch("app.api.unified_chat.MemoryService", return_value=memory_service):
            await unified_chat_stream(request, db, {"user_id": 7, "role": "customer"})

        route_agent.route.assert_awaited_once_with(
            message="test", session_id="", user_id=7, user_role="customer"
        )
        memory_service.archive_turn.assert_awaited_once_with(
            "fresh-server-session", 7, "operator", "test", "done"
        )


if __name__ == "__main__":
    unittest.main()
