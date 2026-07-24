import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import Mock


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


if __name__ == "__main__":
    unittest.main()
