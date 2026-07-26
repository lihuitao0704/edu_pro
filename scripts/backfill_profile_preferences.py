"""Backfill missing profile preferences from the active product catalogue."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import get_settings
from app.service.profile_preference_backfill import (
    build_missing_profile_fields,
    build_product_preference,
)


PROFILE_QUERY = """SELECT customer_id, risk_level_code, risk_level_name,
                          asset_allocation, product_preference
                   FROM fin_customer_profile
                   ORDER BY customer_id
                   FOR UPDATE"""
PRODUCT_QUERY = """SELECT id, product_code, product_name, product_type, risk_level, status
                   FROM fin_product
                   WHERE status = '在售'
                   ORDER BY risk_level, product_code
                   FOR UPDATE"""
CANDIDATE_ROWS_SQL = """fin_customer_profile p
    JOIN JSON_TABLE(
        p.product_preference,
        '$.candidate_products[*]' COLUMNS (
            product_id BIGINT PATH '$.product_id',
            product_code VARCHAR(32) PATH '$.product_code',
            risk_level VARCHAR(8) PATH '$.risk_level'
        )
    ) candidate"""
PRODUCT_CODE_MATCH_SQL = (
    "product.product_code = candidate.product_code COLLATE utf8mb4_unicode_ci"
)
INVALID_CANDIDATE_LIST_SQL = """SELECT COUNT(*) AS count
    FROM fin_customer_profile
    WHERE product_preference IS NULL
       OR JSON_LENGTH(JSON_EXTRACT(product_preference, '$.candidate_products')) IS NULL
       OR JSON_LENGTH(JSON_EXTRACT(product_preference, '$.candidate_products')) = 0"""
EXCESSIVE_PRODUCT_RISK_SQL = f"""SELECT COUNT(*) AS count FROM {CANDIDATE_ROWS_SQL}
    JOIN fin_product product
      ON product.id = candidate.product_id
     AND {PRODUCT_CODE_MATCH_SQL}
    WHERE CAST(SUBSTRING(product.risk_level, 2) AS UNSIGNED)
        > CAST(SUBSTRING(p.risk_level_code, 2) AS UNSIGNED)"""


def build_updates(
    profiles: list[dict[str, Any]],
    products: list[dict[str, Any]],
    generated_at: str,
    *,
    replace_generated_product_preferences: bool = False,
) -> list[dict[str, Any]]:
    """Build update payloads without modifying the supplied database records."""
    updates: list[dict[str, Any]] = []
    for profile in profiles:
        fields = build_missing_profile_fields(profile, products, generated_at)
        preference = profile.get("product_preference")
        if (
            replace_generated_product_preferences
            and _is_generated_preference(preference)
        ):
            risk_level = profile.get("risk_level_code") or profile.get("risk_level_name")
            fields["product_preference"] = build_product_preference(
                risk_level, products, generated_at
            )
        if fields:
            updates.append({"customer_id": profile["customer_id"], **fields})
    return updates


def _is_generated_preference(value: Any) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return False
    return isinstance(value, dict) and bool(value.get("generated_at"))


def _load_profiles(cursor: pymysql.cursors.Cursor) -> list[dict[str, Any]]:
    cursor.execute(PROFILE_QUERY)
    return list(cursor.fetchall())


def _load_products(cursor: pymysql.cursors.Cursor) -> list[dict[str, Any]]:
    cursor.execute(PRODUCT_QUERY)
    return list(cursor.fetchall())


def _write_update(
    cursor: pymysql.cursors.Cursor,
    update: dict[str, Any],
    *,
    replace_generated_product_preferences: bool,
) -> tuple[int, int]:
    customer_id = update["customer_id"]
    allocation_rows = 0
    preference_rows = 0
    if "asset_allocation" in update:
        cursor.execute(
            """UPDATE fin_customer_profile
               SET asset_allocation = %s, update_time = NOW()
               WHERE customer_id = %s
                 AND (asset_allocation IS NULL OR JSON_LENGTH(asset_allocation) = 0)""",
            (json.dumps(update["asset_allocation"], ensure_ascii=False), customer_id),
        )
        allocation_rows = cursor.rowcount
    if "product_preference" in update:
        preference_condition = (
            "(product_preference IS NULL OR JSON_LENGTH(product_preference) = 0)"
        )
        if replace_generated_product_preferences:
            preference_condition = (
                f"({preference_condition} OR "
                "JSON_EXTRACT(product_preference, '$.generated_at') IS NOT NULL)"
            )
        cursor.execute(
            f"""UPDATE fin_customer_profile
               SET product_preference = %s, update_time = NOW()
               WHERE customer_id = %s
                 AND {preference_condition}""",
            (json.dumps(update["product_preference"], ensure_ascii=False), customer_id),
        )
        preference_rows = cursor.rowcount
    return allocation_rows, preference_rows


def _count(cursor: pymysql.cursors.Cursor, sql: str) -> int:
    cursor.execute(sql)
    row = cursor.fetchone()
    return int(row["count"])


def validate(cursor: pymysql.cursors.Cursor) -> dict[str, int]:
    """Return independent validation counts for the persisted profile data."""
    return {
        "missing_preference_fields": _count(
            cursor,
            """SELECT COUNT(*) AS count FROM fin_customer_profile
               WHERE asset_allocation IS NULL OR JSON_LENGTH(asset_allocation) = 0
                  OR product_preference IS NULL OR JSON_LENGTH(product_preference) = 0""",
        ),
        "invalid_candidate_lists": _count(cursor, INVALID_CANDIDATE_LIST_SQL),
        "invalid_allocation_totals": _count(
            cursor,
            """SELECT COUNT(*) AS count FROM fin_customer_profile
               WHERE ABS(
                   COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(asset_allocation, '$.cash')) AS DECIMAL(8, 4)), -1)
                 + COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(asset_allocation, '$.bond')) AS DECIMAL(8, 4)), -1)
                 + COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(asset_allocation, '$.hybrid')) AS DECIMAL(8, 4)), -1)
                 + COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(asset_allocation, '$.equity')) AS DECIMAL(8, 4)), -1)
                 - 1.00) > 0.0001""",
        ),
        "missing_product_references": _count(
            cursor,
            f"""SELECT COUNT(*) AS count FROM {CANDIDATE_ROWS_SQL}
                LEFT JOIN fin_product product
                  ON product.id = candidate.product_id
                 AND {PRODUCT_CODE_MATCH_SQL}
                WHERE product.id IS NULL""",
        ),
        "off_sale_product_references": _count(
            cursor,
            f"""SELECT COUNT(*) AS count FROM {CANDIDATE_ROWS_SQL}
                JOIN fin_product product
                  ON product.id = candidate.product_id
                 AND {PRODUCT_CODE_MATCH_SQL}
                WHERE product.status <> '在售'""",
        ),
        "excessive_product_risk": _count(
            cursor,
            EXCESSIVE_PRODUCT_RISK_SQL,
        ),
    }


def backfill(*, apply: bool, replace_generated_product_preferences: bool = False) -> dict[str, Any]:
    """Preview or execute the profile preference backfill in one transaction."""
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=settings.mysql.database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            profiles = _load_profiles(cursor)
            products = _load_products(cursor)
            updates = build_updates(
                profiles,
                products,
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                replace_generated_product_preferences=replace_generated_product_preferences,
            )
            summary: dict[str, Any] = {
                "apply": apply,
                "profiles_scanned": len(profiles),
                "planned_profiles": len(updates),
                "planned_asset_allocation_updates": sum("asset_allocation" in item for item in updates),
                "planned_product_preference_updates": sum("product_preference" in item for item in updates),
            }
            if not apply:
                connection.rollback()
                return summary
            updated_customer_ids: set[int] = set()
            allocation_updates = 0
            preference_updates = 0
            for update in updates:
                allocation_rows, preference_rows = _write_update(
                    cursor,
                    update,
                    replace_generated_product_preferences=replace_generated_product_preferences,
                )
                if allocation_rows or preference_rows:
                    updated_customer_ids.add(update["customer_id"])
                allocation_updates += allocation_rows
                preference_updates += preference_rows
            validation = validate(cursor)
            summary["updated_profiles"] = len(updated_customer_ids)
            summary["asset_allocation_updates"] = allocation_updates
            summary["product_preference_updates"] = preference_updates
            summary["validation"] = validation
            if any(validation.values()):
                raise RuntimeError(f"画像偏好回填校验失败: {validation}")
        connection.commit()
        return summary
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-backfill-profile-preferences", action="store_true")
    parser.add_argument("--replace-generated-product-preferences", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.confirm_backfill_profile_preferences:
        parser.error("执行写入必须同时传入 --confirm-backfill-profile-preferences")
    print(json.dumps(
        backfill(
            apply=args.apply,
            replace_generated_product_preferences=args.replace_generated_product_preferences,
        ),
        ensure_ascii=False,
        default=str,
    ))
