import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class QuestionnaireConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_questionnaire_submission_updates_tag_archives_score_and_uses_datetime(self):
        from app.model.schemas import AssessmentAnswer
        from app.service.risk_service import RiskService

        profile = SimpleNamespace(risk_level=None, risk_score=None, update_time=None)
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: profile),
                SimpleNamespace(scalar_one_or_none=lambda: None),
            ]),
            add=lambda _: None,
            flush=AsyncMock(),
            commit=AsyncMock(),
        )
        service = RiskService(db)
        service.cache.invalidate = AsyncMock()
        answers = [AssessmentAnswer(q=index, a="D") for index in range(1, 17)]

        with patch.object(service.long_term, 'archive_rating_record', new=AsyncMock()) as archive, \
             patch('app.service.risk_service.sync_risk_level', new=AsyncMock()) as sync:
            result = await service.submit_assessment(7, answers)

        self.assertLessEqual(result.total_score, 100)
        self.assertEqual(result.total_score, profile.risk_score)
        self.assertIsNotNone(profile.update_time)
        archive.assert_awaited_once()
        db.commit.assert_awaited_once()
        sync.assert_awaited_once_with(7, result.risk_level)
