from app.service.advisor_narrative_service import AdvisorNarrativeService


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
