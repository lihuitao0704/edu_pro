import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace


class ProfileScoreHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_endpoint_returns_ascending_chart_fields_and_enforces_customer_scope(self):
        from app.api.profile import get_score_history

        newer = SimpleNamespace(
            create_time=datetime(2026, 7, 20, 10), rating_date=datetime(2026, 7, 20, 9),
            total_score=Decimal('72.5'), risk_level='C3', basic_score=Decimal('70'),
            experience_score=Decimal('68'), risk_pref_score=Decimal('74'), behavior_score=Decimal('78'), trigger_type='auto',
        )
        older = SimpleNamespace(
            create_time=datetime(2026, 7, 10, 10), rating_date=datetime(2026, 7, 10, 9),
            total_score=Decimal('66'), risk_level='C2', basic_score=Decimal('62'),
            experience_score=Decimal('64'), risk_pref_score=Decimal('69'), behavior_score=Decimal('70'), trigger_type='manual',
        )

        db = SimpleNamespace()
        from unittest.mock import AsyncMock, patch
        with patch('app.api.profile.LongTermMemory.get_rating_history', new=AsyncMock(return_value=[newer, older])):
            result = await get_score_history(7, db, {'user_id': 7, 'role': '客户'})

        records = result['data']
        self.assertEqual(['2026-07-10', '2026-07-20'], [row['rating_date'] for row in records])
        self.assertEqual(66.0, records[0]['total_score'])
        self.assertEqual('manual', records[0]['trigger_type'])
        self.assertEqual('C3', records[1]['risk_level'])

