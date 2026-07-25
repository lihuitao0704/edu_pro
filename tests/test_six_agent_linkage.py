import unittest
from unittest.mock import AsyncMock

from app.service.transaction_flow_service import TransactionFlowService
from app.service.profile_service import ProfileService
from app.service.advisor_service import AdvisorService
from app.service.insight_extractor import extract_analytics_insights
from app.service.customer_sentiment import detect_customer_sentiment


class _RiskRule:
    rule_id = "R001"
    rule_name = "大额现金交易"
    risk_level = "高"
    weight = 1.0
    trigger_condition = "金额超过阈值"


class _HighRiskMonitor:
    def evaluate_all(self, event):
        return [_RiskRule()]

    async def get_alerts(self, db, **kwargs):
        return 0, []

    def grade(self, triggered, history, event):
        return "high"

    def build_alert(self, event, triggered, level, confidence):
        return {
            "customer_id": event["customer_id"],
            "transaction_id": event["transaction_id"],
            "alert_level": level,
            "trigger_rules": [{"rule_id": "R001"}],
            "confidence": confidence,
            "summary": "高风险交易",
            "recommendation": "阻止执行",
        }

    async def save_alert(self, db, alert):
        return 88


class TransactionPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_high_risk_preflight_blocks_before_operation(self):
        flow = TransactionFlowService(monitor=_HighRiskMonitor())
        flow.enrich_context = AsyncMock(
            return_value={
                "customer_id": 27,
                "transaction_id": "TX-001",
                "amount": 1_000_000,
                "transaction_type": "transfer_out",
            }
        )

        result = await flow.assess_pre_execution(db=object(), event={"customer_id": 27})

        self.assertEqual("block", result["decision"])
        self.assertEqual(88, result["alert"]["alert_id"])


class RecommendationFeedbackTests(unittest.TestCase):
    def test_three_rejections_add_product_type_to_avoid_constraints(self):
        preference = {}
        event = {"product_type": "混合基金", "status": "rejected", "reason": "波动过大"}

        for _ in range(3):
            preference = ProfileService.merge_recommendation_feedback(preference, event)

        self.assertIn("混合基金", preference["avoid_product_types"])
        self.assertEqual(3, preference["feedback_signals"]["混合基金"]["rejected_count"])

    def test_candidate_filter_excludes_rejected_product_type(self):
        candidates = [
            {"product_code": "F1", "product_type": "混合基金"},
            {"product_code": "F2", "product_type": "债券基金"},
        ]

        filtered = AdvisorService.filter_candidates_by_preferences(
            candidates, {"avoid_product_types": ["混合基金"]}
        )

        self.assertEqual(["F2"], [item["product_code"] for item in filtered])


class AnalyticsInsightTests(unittest.TestCase):
    def test_verifiable_drawdown_produces_profile_safe_signal(self):
        events = extract_analytics_insights(
            "客户27近30日亏损情况",
            [{"customer_id": 27, "profit_ratio": -0.12, "period_days": 30}],
        )

        self.assertEqual("analytics_insight", events[0].event_type)
        self.assertEqual("pnl_drawdown", events[0].payload["kind"])
        self.assertEqual(27, events[0].customer_id)

    def test_non_customer_free_text_result_does_not_create_event(self):
        self.assertEqual([], extract_analytics_insights("市场怎么样", [{"summary": "波动"}]))


class CustomerSentimentTests(unittest.TestCase):
    def test_high_distress_is_extracted_from_customer_message(self):
        result = detect_customer_sentiment("我亏惨了，特别焦虑，今晚睡不着")

        self.assertEqual("high_distress", result["level"])
        self.assertTrue(result["keywords"])
