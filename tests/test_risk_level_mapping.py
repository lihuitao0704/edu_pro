import pytest


def test_normalize_accepts_code_name_and_legacy_alias():
    from app.config.risk_level_mapping import normalize_risk_level

    assert normalize_risk_level(" c3 ").model_dump() == {
        "risk_level_code": "C3",
        "risk_level_name": "平衡型",
    }
    assert normalize_risk_level("积极型").model_dump() == {
        "risk_level_code": "C4",
        "risk_level_name": "积极型",
    }
    assert normalize_risk_level("进取型").model_dump() == {
        "risk_level_code": "C4",
        "risk_level_name": "积极型",
    }


def test_normalize_rejects_product_or_unknown_risk_level():
    from app.config.risk_level_mapping import (
        RiskLevelNormalizationError,
        normalize_risk_level,
    )

    with pytest.raises(RiskLevelNormalizationError):
        normalize_risk_level("R3")
    with pytest.raises(RiskLevelNormalizationError):
        normalize_risk_level("未知型")


@pytest.mark.parametrize(
    ("score", "code", "name"),
    [
        (0, "C1", "保守型"),
        (25, "C1", "保守型"),
        (26, "C2", "稳健型"),
        (40, "C2", "稳健型"),
        (41, "C3", "平衡型"),
        (60, "C3", "平衡型"),
        (61, "C4", "积极型"),
        (80, "C4", "积极型"),
        (81, "C5", "激进型"),
        (100, "C5", "激进型"),
    ],
)
def test_score_mapping_uses_the_standard_pairs(score, code, name):
    from app.config.risk_level_mapping import risk_level_from_score

    assert risk_level_from_score(score).model_dump() == {
        "risk_level_code": code,
        "risk_level_name": name,
    }
