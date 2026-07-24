import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


class PlatformPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_turn_persistence_creates_session_messages_entity_and_trace(self):
        from app.common_services.platform_persistence import PlatformPersistenceService
        from app.model.schemas import UnifiedChatResponse

        db = SimpleNamespace(
            get=AsyncMock(return_value=None), add=Mock(), commit=AsyncMock(), rollback=AsyncMock()
        )
        response = UnifiedChatResponse(
            intent="product_faq", agent="customer_service", confidence=0.9,
            session_id="s-1", reply="答复", data={
                "trace_id": "tr-1",
                "context": {"entities": {"product_name": "稳健增长混合A"}},
            },
        )

        await PlatformPersistenceService(db).persist_turn(7, "问题", response)

        self.assertEqual(5, db.add.call_count)
        db.commit.assert_awaited_once()


class FeedbackServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_low_rating_flags_owned_session(self):
        from app.common_services.feedback_service.feedback_service import FeedbackService

        session = SimpleNamespace(user_id=7, flagged=False, last_intent="product_faq", last_agent="customer_service")
        db = SimpleNamespace(get=AsyncMock(return_value=session), add=Mock(), commit=AsyncMock())

        result = await FeedbackService(db).submit(7, "s-1", 2, "回答不准确")

        self.assertTrue(session.flagged)
        self.assertTrue(result["low_rating_alert"])
        db.commit.assert_awaited_once()


class AnalyticsServiceTests(unittest.TestCase):
    def test_aggregate_returns_dashboard_shape(self):
        from app.common_services.analytics_service.analytics_service import ChatAnalyticsService

        rows = [
            SimpleNamespace(intent="product_query", agent_name="investment_agent", session_count=2,
                            turn_count=3, avg_rating=4.5, fallback_rate=0.1, avg_response_ms=2000),
            SimpleNamespace(intent="risk", agent_name="risk_agent", session_count=1,
                            turn_count=1, avg_rating=4.0, fallback_rate=0.2, avg_response_ms=3000),
        ]

        result = ChatAnalyticsService.aggregate(rows, today_sessions=1)

        self.assertEqual(3, result["total_sessions"])
        self.assertEqual(4.25, result["avg_rating"])
        self.assertEqual(2.5, result["avg_response_time"])


if __name__ == "__main__":
    unittest.main()
