import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.model.entities import FinCustomerProfile
from app.service.profile_service import PROFILE_CACHE_SCHEMA_VERSION, ProfileService


class ProfileCacheContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_risk_level_cache_is_ignored_after_contract_upgrade(self):
        database_profile = FinCustomerProfile(
            customer_id=11,
            risk_level_code="C2",
            risk_level_name="稳健型",
            risk_score=42,
        )
        db = AsyncMock()
        db.execute.return_value = SimpleNamespace(
            scalar_one_or_none=lambda: database_profile,
        )
        service = ProfileService(db)
        service.cache = SimpleNamespace(
            get=AsyncMock(
                return_value={
                    "_schema_version": 2,
                    "customer_id": 11,
                    "risk_level": "稳健型",
                    "risk_score": 42,
                }
            ),
            set=AsyncMock(),
        )

        profile = await service.get_profile(11)

        self.assertIs(profile, database_profile)
        db.execute.assert_awaited_once()
        service.cache.set.assert_awaited_once()

    async def test_cache_hit_returns_same_model_contract_as_database_hit(self):
        service = ProfileService(AsyncMock())
        service.cache = SimpleNamespace(
            get=AsyncMock(
                return_value={
                    "_schema_version": PROFILE_CACHE_SCHEMA_VERSION,
                    "customer_id": 11,
                    "risk_level_code": "C2",
                    "risk_level_name": "稳健型",
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
