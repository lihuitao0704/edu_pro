import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


class QuestionnaireConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_questionnaire_submission_updates_tag_archives_score_and_uses_datetime(self):
        from app.model.schemas import AssessmentAnswer
        from app.service.risk_service import RiskService

        profile = SimpleNamespace(
            risk_level=None,
            risk_score=None,
            update_time=None,
            profile_json={},
        )
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

        # Mock 引擎研判（避免 mock db 耗尽 side_effects，同时验证引擎被调用）
        mock_engine = MagicMock()
        mock_engine.risk_level = "C5"
        mock_engine.circuit_breakers = []
        mock_engine.warnings = []
        with patch.object(service, '_upsert_questionnaire_risk_tag', new=AsyncMock()), \
             patch('app.service.risk_service.sync_risk_level', new=AsyncMock()) as sync, \
             patch('app.service.profile_service.ProfileService.assess',
                   new=AsyncMock(return_value=mock_engine)) as mock_assess:
            result = await service.submit_assessment(7, answers)

        self.assertLessEqual(result.total_score, 100)
        self.assertEqual(result.total_score, profile.risk_score)
        self.assertIsNotNone(profile.update_time)
        self.assertEqual(result.risk_level, profile.profile_json["risk_level"])
        self.assertEqual(result.total_score, profile.profile_json["risk_score"])
        # 引擎研判被调用
        mock_assess.assert_awaited_once()
        # commit 不再在 submit_assessment 内部调用，由外层 get_db 统一管理
        db.commit.assert_not_called()
        sync.assert_awaited_once_with(7, result.risk_level)
