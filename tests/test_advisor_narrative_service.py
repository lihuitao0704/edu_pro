from app.service.advisor_narrative_service import AdvisorNarrativeService
from app.common_services.context_manager.models import AgentResult
from app.common_services.orchestration.response_enhancer import ResponseEnhancer


def test_narrative_fallback_includes_risk_disclaimer():
    narrative = AdvisorNarrativeService.render_template(
        {"customer_profile": {"assessment": {"risk_level": "C3"}}, "recommendations": [{"product_name": "稳健债券A"}]}
    )

    assert "稳健债券A" in narrative
    assert "投资有风险，入市需谨慎" in narrative


def test_existing_llm_copy_is_normalized_with_risk_disclaimer():
    narrative = AdvisorNarrativeService.ensure_disclaimer("已基于客户画像完成匹配。")

    assert narrative.startswith("已基于客户画像")
    assert "投资有风险，入市需谨慎" in narrative


def test_customer_narrative_hides_internal_alert_details_and_prompt_leakage():
    narrative = AdvisorNarrativeService.render_customer({
        "customer_profile": {
            "assessment": {"risk_level": "C3"},
            "total_assets": 9_144_101,
        },
        "risk_alerts": {
            "alert_level": "high",
            "status": "pending",
            "escalation_reason": "超过3天自动升级为红色预警",
        },
        "recommendations": [{
            "product_name": "稳健债券A",
            "risk_level": "R2",
            "product_type": "债券型",
            "expected_return": 4.2,
            "reason": "我们被要求生成个性化推荐理由，需引用画像信息，50字以内。",
        }],
    })

    assert "C3" in narrative
    assert "稳健债券A" in narrative
    assert "风险事项待确认" in narrative
    assert "超过3天" not in narrative
    assert "红色预警" not in narrative
    assert "9,144,101" not in narrative
    assert "我们被要求" not in narrative
    assert narrative.count("投资有风险") == 1


def test_semantically_equivalent_disclaimer_is_not_duplicated():
    text = (
        "已完成产品筛选。\n\n"
        "投资有风险，请谨慎决策。以上推荐不构成投资建议。"
    )

    narrative = AdvisorNarrativeService.ensure_disclaimer(text)

    assert narrative == text


def test_completed_structured_recommendation_does_not_append_redundant_questions():
    result = AgentResult(
        reply="已完成产品筛选。",
        intent="investment_recommendation",
        agent_name="advisor",
        confidence=0.9,
        source_count=0,
        data={"recommendations": [{"product_name": "稳健债券A"}]},
    )

    enhanced = ResponseEnhancer().enhance(result)

    assert enhanced.reply == "已完成产品筛选。"
    assert enhanced.suggested_questions == []
