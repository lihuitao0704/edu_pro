import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class WorkspaceRouteTests(unittest.TestCase):
    def test_required_workspace_routes_are_registered(self):
        from main import app

        paths = set(app.openapi()["paths"])
        required = {
            "/api/customers",
            "/api/customers/{customer_id}",
            "/api/customers/{customer_id}/holdings",
            "/api/operation/workorders",
            "/api/operation/workorder/{work_order_id}",
            "/api/operation/workorder/{work_order_id}/handle",
            "/api/knowledge/status",
        }

        self.assertTrue(required.issubset(paths), required - paths)


class ProfileResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_response_exposes_risk_flag(self):
        from app.api.profile import get_profile

        profile = SimpleNamespace(
            customer_id=3,
            risk_level="稳健型",
            risk_score=52,
            confidence_score=Decimal("0.80"),
            basic_score=Decimal("12"),
            experience_score=Decimal("14"),
            risk_pref_score=Decimal("15"),
            behavior_score=Decimal("11"),
            total_assets=Decimal("500000"),
            investment_experience="3-5年",
            annual_income_range="30-50万",
            risk_flag="warning",
            update_time=None,
        )

        with patch(
            "app.api.profile.ProfileService.get_profile",
            new=AsyncMock(return_value=profile),
        ):
            response = await get_profile(
                3, db=object(), user={"user_id": 2, "role": "理财顾问"}
            )

        self.assertEqual("warning", response["data"]["risk_flag"])


if __name__ == "__main__":
    unittest.main()
