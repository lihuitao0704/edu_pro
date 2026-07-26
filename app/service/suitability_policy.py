"""Single source of truth for investor/product suitability decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


RULE_VERSION = "suitability-v2"
DISCLOSURE_DOCUMENT = "《产品风险超越投资者风险承受能力揭示书》"

_CUSTOMER_LEVEL_ALIASES = {
    "保守型": "C1",
    "稳健型": "C2",
    "平衡型": "C3",
    "进取型": "C4",
    "激进型": "C5",
    "R1": "C1",
    "R2": "C2",
    "R3": "C3",
    "R4": "C4",
    "R5": "C5",
}

_ALLOWED_PRODUCT_LEVELS = {
    "C1": ("R1", "R2"),
    "C2": ("R1", "R2", "R3"),
    "C3": ("R1", "R2", "R3", "R4"),
    "C4": ("R1", "R2", "R3", "R4", "R5"),
    "C5": ("R1", "R2", "R3", "R4", "R5"),
}

_DISCLOSURE_RULES = {
    ("C3", "R4"): {
        "rule_code": "SD-C3-R4",
        "max_position_ratio": 0.20,
    },
    ("C4", "R5"): {
        "rule_code": "SD-C4-R5",
        "max_position_ratio": 0.10,
    },
}


@dataclass(frozen=True)
class SuitabilityDecision:
    customer_level: str
    product_level: str
    allowed: bool
    disclosure_required: bool
    allowed_product_levels: tuple[str, ...]
    rule_version: str = RULE_VERSION
    rule_code: str | None = None
    disclosure_document: str | None = None
    max_position_ratio: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def disclosure_text(self) -> str | None:
        if not self.disclosure_required:
            return None
        percentage = int(float(self.max_position_ratio or 0) * 100)
        return (
            f"{self.customer_level} 客户购买 {self.product_level} 产品前，"
            f"必须阅读并确认{self.disclosure_document}；"
            f"购买后该产品持仓不得超过总资产的 {percentage}%"
        )


def normalize_customer_level(level: str | None) -> str:
    normalized = str(level or "").strip().upper()
    return _CUSTOMER_LEVEL_ALIASES.get(normalized, normalized)


def normalize_product_level(level: str | None) -> str:
    normalized = str(level or "").strip().upper()
    if normalized in _CUSTOMER_LEVEL_ALIASES:
        return normalize_customer_level(normalized).replace("C", "R", 1)
    return normalized


def evaluate_suitability(
    customer_level: str | None,
    product_level: str | None,
) -> SuitabilityDecision:
    customer = normalize_customer_level(customer_level)
    product = normalize_product_level(product_level)
    allowed_levels = _ALLOWED_PRODUCT_LEVELS.get(customer, ())
    disclosure_rule = _DISCLOSURE_RULES.get((customer, product))
    return SuitabilityDecision(
        customer_level=customer,
        product_level=product,
        allowed=bool(product and product in allowed_levels),
        disclosure_required=disclosure_rule is not None,
        allowed_product_levels=allowed_levels,
        rule_code=disclosure_rule["rule_code"] if disclosure_rule else None,
        disclosure_document=DISCLOSURE_DOCUMENT if disclosure_rule else None,
        max_position_ratio=(
            float(disclosure_rule["max_position_ratio"])
            if disclosure_rule
            else None
        ),
    )


def validate_disclosure_ack(
    acknowledgement: Any,
    decision: SuitabilityDecision,
) -> bool:
    if not decision.disclosure_required:
        return True
    if not isinstance(acknowledgement, dict):
        return False
    return (
        acknowledgement.get("accepted") is True
        and acknowledgement.get("rule_version") == decision.rule_version
        and acknowledgement.get("rule_code") == decision.rule_code
        and acknowledgement.get("customer_level") == decision.customer_level
        and acknowledgement.get("product_level") == decision.product_level
        and bool(acknowledgement.get("acknowledged_at"))
    )
