import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.model.entities import FinCustomerProfile
from app.service.profile_service import ProfileService


class ProfileCacheContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_hit_returns_same_model_contract_as_database_hit(self):
        service = ProfileService(AsyncMock())
        service.cache = SimpleNamespace(
            get=AsyncMock(
                return_value={
                    "_schema_version": 2,
                    "customer_id": 11,
                    "risk_level": "C2",
                    "risk_score": 42,
                    "confidence_score": "0.82",
                    "total_assets": "500000",
                    "risk_flag": "normal",
                }
            ),
            set=AsyncMock(),
        )

        profile = await service.get_profile(11)

        self.assertIsInstance(profile, FinCustomerProfile)
        self.assertEqual(11, profile.customer_id)
        self.assertEqual("0.82", profile.confidence_score)
        self.assertEqual("normal", profile.risk_flag)
        service.db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
