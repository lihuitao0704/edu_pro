"""Build safe, catalogue-backed customer preference data for backfill jobs."""

from __future__ import annotations

import json
from typing import Any

from app.config.risk_level_mapping import normalize_risk_level


_ALLOCATIONS: dict[str, dict[str, float]] = {
    "C1": {"cash": 0.30, "bond": 0.55, "hybrid": 0.15, "equity": 0.00},
    "C2": {"cash": 0.20, "bond": 0.45, "hybrid": 0.25, "equity": 0.10},
    "C3": {"cash": 0.15, "bond": 0.35, "hybrid": 0.30, "equity": 0.20},
    "C4": {"cash": 0.10, "bond": 0.20, "hybrid": 0.35, "equity": 0.35},
    "C5": {"cash": 0.05, "bond": 0.10, "hybrid": 0.25, "equity": 0.60},
}

_PREFERRED_PRODUCT_TYPES: dict[str, list[str]] = {
    "C1": ["货币", "债券", "混合"],
    "C2": ["债券", "货币", "混合", "股票"],
    "C3": ["债券", "混合", "股票", "货币"],
    "C4": ["股票", "混合", "债券", "货币"],
    "C5": ["股票", "混合", "债券", "货币"],
}


def _risk_number(value: Any, prefix: str) -> int:
    if not isinstance(value, str) or len(value) != 2 or value[0].upper() != prefix:
        raise ValueError(f"无效的产品风险等级: {value!r}")
    try:
        number = int(value[1])
    except ValueError as exc:
        raise ValueError(f"无效的产品风险等级: {value!r}") from exc
    if number not in range(1, 6):
        raise ValueError(f"无效的产品风险等级: {value!r}")
    return number


def build_asset_allocation(risk_code: str) -> dict[str, float]:
    """Return a copy of the canonical allocation template for one risk code."""
    code = normalize_risk_level(risk_code).risk_level_code
    return dict(_ALLOCATIONS[code])


def build_product_preference(
    risk_code: str,
    products: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    """Create preference JSON using only exact, in-sale catalogue records."""
    normalized = normalize_risk_level(risk_code)
    maximum_risk = _risk_number(normalized.risk_level_code, "C")
    allowed_risks = [f"R{number}" for number in range(1, maximum_risk + 1)]
    candidates = [
        product
        for product in products
        if product.get("status") == "在售"
        and _risk_number(product.get("risk_level"), "R") <= maximum_risk
        and product.get("id") is not None
        and product.get("product_code")
    ]
    candidates.sort(key=lambda product: (_risk_number(product["risk_level"], "R"), product["product_code"]))
    selected = candidates[:3]
    if not selected:
        raise ValueError("没有可用在售产品")

    return {
        "risk_level_code": normalized.risk_level_code,
        "risk_level_name": normalized.risk_level_name,
        "allowed_product_risk_levels": allowed_risks,
        "preferred_product_types": _PREFERRED_PRODUCT_TYPES[normalized.risk_level_code],
        "candidate_products": [
            {
                "product_id": product["id"],
                "product_code": product["product_code"],
                "product_name": product.get("product_name"),
                "product_type": product.get("product_type"),
                "risk_level": product["risk_level"],
            }
            for product in selected
        ],
        "generated_at": generated_at,
    }


def is_empty_json(value: object) -> bool:
    """Treat null, blank and empty JSON objects as eligible for backfill."""
    if value is None or value == "" or value == {}:
        return True
    if isinstance(value, str):
        try:
            return json.loads(value) == {}
        except json.JSONDecodeError:
            return False
    return False


def build_missing_profile_fields(
    profile: dict[str, Any],
    products: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, dict[str, Any]]:
    """Build values exclusively for empty profile preference fields."""
    risk_level = profile.get("risk_level_code") or profile.get("risk_level_name")
    updates: dict[str, dict[str, Any]] = {}
    if is_empty_json(profile.get("asset_allocation")):
        updates["asset_allocation"] = build_asset_allocation(risk_level)
    if is_empty_json(profile.get("product_preference")):
        updates["product_preference"] = build_product_preference(
            risk_level, products, generated_at
        )
    return updates
