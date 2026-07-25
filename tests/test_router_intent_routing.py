from app.service.intent_service import IntentService


def test_risk_signal_overrides_a_transfer_operation():
    intent, confidence, _ = IntentService._keyword_quick_route("发现可疑转账，请马上核查")

    assert intent == "risk_control"
    assert confidence == 0.95


def test_recommendation_does_not_fall_into_business_operation():
    intent, _, _ = IntentService._keyword_quick_route("请为我推荐适合稳健型客户的产品")

    assert intent == "investment_recommendation"


def test_portfolio_analysis_is_an_investment_intent():
    intent, _, _ = IntentService._keyword_quick_route("帮我分析当前持仓的行业分布和集中度")

    assert intent == "investment_recommendation"


def test_explicit_purchase_remains_a_business_operation():
    intent, _, _ = IntentService._keyword_quick_route("我要申购产品 F200001")

    assert intent == "business_operation"
