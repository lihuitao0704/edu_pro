"""Canonical customer-investor risk-level mapping and normalization."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


RISK_LEVEL_MAPPING: dict[str, str] = {
    "C1": "保守型",
    "C2": "稳健型",
    "C3": "平衡型",
    "C4": "积极型",
    "C5": "激进型",
}

RISK_LEVEL_SCORE_BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 25, "C1"),
    (26, 40, "C2"),
    (41, 60, "C3"),
    (61, 80, "C4"),
    (81, 100, "C5"),
)

_INPUT_TO_CODE = {
    **{code: code for code in RISK_LEVEL_MAPPING},
    **{name: code for code, name in RISK_LEVEL_MAPPING.items()},
    "进取型": "C4",
}


class RiskLevelNormalizationError(ValueError):
    """Raised when a value is not a customer-investor risk level."""


class NormalizedRiskLevel(BaseModel):
    """The only valid customer-risk representation at system boundaries."""

    model_config = ConfigDict(frozen=True)

    risk_level_code: str
    risk_level_name: str


def normalize_risk_level(value: str | NormalizedRiskLevel) -> NormalizedRiskLevel:
    """Normalize a code, standard Chinese name, or approved legacy alias."""
    if isinstance(value, NormalizedRiskLevel):
        return value
    if not isinstance(value, str):
        raise RiskLevelNormalizationError("风险等级必须是 C1-C5 编码或标准名称")

    normalized_value = value.strip()
    code = _INPUT_TO_CODE.get(normalized_value.upper()) or _INPUT_TO_CODE.get(normalized_value)
    if not code:
        raise RiskLevelNormalizationError(f"无效的客户风险等级: {value!r}")
    return NormalizedRiskLevel(
        risk_level_code=code,
        risk_level_name=RISK_LEVEL_MAPPING[code],
    )


def risk_level_from_score(score: float) -> NormalizedRiskLevel:
    """Map a score to the canonical customer-risk pair with safe bounds."""
    bounded_score = max(0, min(100, float(score)))
    for minimum, maximum, code in RISK_LEVEL_SCORE_BANDS:
        if minimum <= bounded_score <= maximum:
            return normalize_risk_level(code)
    raise AssertionError("bounded score must match one risk-level band")


def is_score_compatible_with_risk_level(score: float, risk_level: str | NormalizedRiskLevel) -> bool:
    """Return whether a score belongs to the normalized level's configured band."""
    code = normalize_risk_level(risk_level).risk_level_code
    return any(
        band_code == code and minimum <= float(score) <= maximum
        for minimum, maximum, band_code in RISK_LEVEL_SCORE_BANDS
    )
