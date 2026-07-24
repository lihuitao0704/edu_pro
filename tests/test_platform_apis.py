import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class PlatformApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_uses_authenticated_actor(self):
        from app.api.feedback import FeedbackRequest, submit_feedback

        service = SimpleNamespace(submit=AsyncMock(return_value={"rating": 5, "low_rating_alert": False}))
        with patch("app.api.feedback.FeedbackService", return_value=service):
            result = await submit_feedback(
                FeedbackRequest(session_id="s-1", rating=5, comment="详细"),
                AsyncMock(), {"user_id": 7, "role": "客户"},
            )
        service.submit.assert_awaited_once_with(7, "s-1", 5, "详细")
        self.assertEqual(5, result["data"]["rating"])


if __name__ == "__main__":
    unittest.main()
