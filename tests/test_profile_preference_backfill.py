import json

import pytest


def test_builds_c3_allocation_and_references_real_allowed_products():
    from app.service.profile_preference_backfill import (
        build_asset_allocation,
        build_product_preference,
    )

    products = [
        {"id": 11, "product_code": "P-R1", "product_name": "货币产品", "product_type": "货币", "risk_level": "R1", "status": "在售"},
        {"id": 12, "product_code": "P-R3", "product_name": "混合产品", "product_type": "混合", "risk_level": "R3", "status": "在售"},
        {"id": 13, "product_code": "P-R4", "product_name": "股票产品", "product_type": "股票", "risk_level": "R4", "status": "在售"},
    ]

    assert build_asset_allocation("C3") == {
        "cash": 0.15,
        "bond": 0.35,
        "hybrid": 0.30,
        "equity": 0.20,
    }

    preference = build_product_preference("C3", products, "2026-07-27T00:00:00Z")

    assert preference["risk_level_code"] == "C3"
    assert preference["allowed_product_risk_levels"] == ["R1", "R2", "R3"]
    assert [item["product_id"] for item in preference["candidate_products"]] == [12, 11]
    assert preference["candidate_products"][0]["product_code"] == "P-R3"


def test_only_builds_missing_fields_and_requires_in_sale_product():
    from app.service.profile_preference_backfill import build_missing_profile_fields

    product = {
        "id": 1,
        "product_code": "P-1",
        "product_name": "货币",
        "product_type": "货币",
        "risk_level": "R1",
        "status": "在售",
    }
    result = build_missing_profile_fields(
        {"risk_level_code": "C1", "asset_allocation": {"cash": 1.0}},
        [product],
        "2026-07-27T00:00:00Z",
    )

    assert "asset_allocation" not in result
    assert result["product_preference"]["candidate_products"][0]["product_id"] == 1

    with pytest.raises(ValueError, match="没有可用在售产品"):
        build_missing_profile_fields({"risk_level_code": "C1"}, [], "2026-07-27T00:00:00Z")


def test_c4_selects_highest_weighted_product_types_at_the_matching_risk_level():
    from app.service.profile_preference_backfill import build_product_preference

    products = [
        {"id": 31, "product_code": "E-R4", "product_name": "股票", "product_type": "股票型", "risk_level": "R4", "status": "在售"},
        {"id": 32, "product_code": "H-R4", "product_name": "混合", "product_type": "混合型", "risk_level": "R4", "status": "在售"},
        {"id": 33, "product_code": "B-R4", "product_name": "债券", "product_type": "债券型", "risk_level": "R4", "status": "在售"},
        {"id": 34, "product_code": "M-R1", "product_name": "货币", "product_type": "货币型", "risk_level": "R1", "status": "在售"},
    ]

    preference = build_product_preference("C4", products, "2026-07-27T00:00:00Z")

    assert [item["product_id"] for item in preference["candidate_products"]] == [31, 32, 33]
    assert [item["risk_level"] for item in preference["candidate_products"]] == ["R4", "R4", "R4"]


def test_backfill_builds_updates_only_for_empty_database_columns():
    from scripts.backfill_profile_preferences import build_updates

    product = {
        "id": 1,
        "product_code": "P-1",
        "product_name": "货币",
        "product_type": "货币",
        "risk_level": "R1",
        "status": "在售",
    }
    updates = build_updates(
        [
            {
                "customer_id": 7,
                "risk_level_code": "C1",
                "asset_allocation": None,
                "product_preference": None,
            },
            {
                "customer_id": 8,
                "risk_level_code": "C1",
                "asset_allocation": {"cash": 1.0},
                "product_preference": {"candidate_products": []},
            },
        ],
        [product],
        "2026-07-27T00:00:00Z",
    )

    assert len(updates) == 1
    assert updates[0]["customer_id"] == 7
    assert updates[0]["asset_allocation"] == {
        "cash": 0.30, "bond": 0.55, "hybrid": 0.15, "equity": 0.00,
    }
    assert updates[0]["product_preference"]["candidate_products"][0]["product_id"] == 1


def test_catalogue_join_uses_the_product_table_collation_for_json_product_codes():
    from scripts.backfill_profile_preferences import PRODUCT_CODE_MATCH_SQL

    assert PRODUCT_CODE_MATCH_SQL == (
        "product.product_code = candidate.product_code COLLATE utf8mb4_unicode_ci"
    )


def test_backfill_sql_locks_catalogue_and_validates_real_product_state():
    from scripts.backfill_profile_preferences import (
        EXCESSIVE_PRODUCT_RISK_SQL,
        INVALID_CANDIDATE_LIST_SQL,
        PRODUCT_QUERY,
        PROFILE_QUERY,
    )

    assert PROFILE_QUERY.rstrip().endswith("FOR UPDATE")
    assert PRODUCT_QUERY.rstrip().endswith("FOR UPDATE")
    assert "product.risk_level" in EXCESSIVE_PRODUCT_RISK_SQL
    assert "$.candidate_products" in INVALID_CANDIDATE_LIST_SQL


def test_replace_mode_updates_only_a_previously_generated_product_preference():
    from scripts.backfill_profile_preferences import build_updates

    product = {
        "id": 1, "product_code": "P-1", "product_name": "货币",
        "product_type": "货币型", "risk_level": "R1", "status": "在售",
    }
    updates = build_updates(
        [{
            "customer_id": 7,
            "risk_level_code": "C1",
            "asset_allocation": {"cash": 0.30, "bond": 0.55, "hybrid": 0.15, "equity": 0.00},
            "product_preference": json.dumps({"generated_at": "2026-07-27T00:00:00Z"}),
        }],
        [product],
        "2026-07-27T01:00:00Z",
        replace_generated_product_preferences=True,
    )

    assert len(updates) == 1
    assert updates[0]["customer_id"] == 7
    assert "asset_allocation" not in updates[0]
    assert updates[0]["product_preference"]["generated_at"] == "2026-07-27T01:00:00Z"
