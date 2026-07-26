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
from app.service.profile_preference_backfill import build_missing_profile_fields


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


def build_updates(
    profiles: list[dict[str, Any]],
    products: list[dict[str, Any]],
    generated_at: str,
) -> list[dict[str, Any]]:
    """Build update payloads without modifying the supplied database records."""
    updates: list[dict[str, Any]] = []
    for profile in profiles:
        fields = build_missing_profile_fields(profile, products, generated_at)
        if fields:
            updates.append({"customer_id": profile["customer_id"], **fields})
    return updates


def _load_profiles(cursor: pymysql.cursors.Cursor) -> list[dict[str, Any]]:
    cursor.execute(
        """SELECT customer_id, risk_level_code, risk_level_name,
                  asset_allocation, product_preference
           FROM fin_customer_profile
           ORDER BY customer_id"""
    )
    return list(cursor.fetchall())


def _load_products(cursor: pymysql.cursors.Cursor) -> list[dict[str, Any]]:
    cursor.execute(
        """SELECT id, product_code, product_name, product_type, risk_level, status
           FROM fin_product
           WHERE status = '在售'
           ORDER BY risk_level, product_code"""
    )
    return list(cursor.fetchall())


def _write_update(cursor: pymysql.cursors.Cursor, update: dict[str, Any]) -> None:
    customer_id = update["customer_id"]
    if "asset_allocation" in update:
        cursor.execute(
            """UPDATE fin_customer_profile
               SET asset_allocation = %s, update_time = NOW()
               WHERE customer_id = %s
                 AND (asset_allocation IS NULL OR JSON_LENGTH(asset_allocation) = 0)""",
            (json.dumps(update["asset_allocation"], ensure_ascii=False), customer_id),
        )
    if "product_preference" in update:
        cursor.execute(
            """UPDATE fin_customer_profile
               SET product_preference = %s, update_time = NOW()
               WHERE customer_id = %s
                 AND (product_preference IS NULL OR JSON_LENGTH(product_preference) = 0)""",
            (json.dumps(update["product_preference"], ensure_ascii=False), customer_id),
        )


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
            f"""SELECT COUNT(*) AS count FROM {CANDIDATE_ROWS_SQL}
                WHERE CAST(SUBSTRING(candidate.risk_level, 2) AS UNSIGNED)
                    > CAST(SUBSTRING(p.risk_level_code, 2) AS UNSIGNED)""",
        ),
    }


def backfill(*, apply: bool) -> dict[str, Any]:
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
            )
            summary: dict[str, Any] = {
                "apply": apply,
                "profiles_scanned": len(profiles),
                "updated_profiles": len(updates),
                "asset_allocation_updates": sum("asset_allocation" in item for item in updates),
                "product_preference_updates": sum("product_preference" in item for item in updates),
            }
            if not apply:
                connection.rollback()
                return summary
            for update in updates:
                _write_update(cursor, update)
            validation = validate(cursor)
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
    args = parser.parse_args()
    if args.apply and not args.confirm_backfill_profile_preferences:
        parser.error("执行写入必须同时传入 --confirm-backfill-profile-preferences")
    print(json.dumps(backfill(apply=args.apply), ensure_ascii=False, default=str))
