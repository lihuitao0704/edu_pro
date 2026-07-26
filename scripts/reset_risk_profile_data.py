"""Safely reset and rebuild only customer-profile and assessment demo data."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta

import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import get_settings
from app.config.risk_level_mapping import (
    RISK_LEVEL_MAPPING,
    is_score_compatible_with_risk_level,
    normalize_risk_level,
)

_BAND_MIDPOINT = {"C1": 18, "C2": 33, "C3": 50, "C4": 70, "C5": 90}


def _dimension_scores(score: int) -> tuple[float, float, float, float]:
    basic = round(score * 0.25, 2)
    experience = round(score * 0.25, 2)
    risk_pref = round(score * 0.30, 2)
    behavior = round(score - basic - experience - risk_pref, 2)
    return basic, experience, risk_pref, behavior


def reset(*, apply: bool) -> dict:
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.mysql.host, port=settings.mysql.port,
        user=settings.mysql.user, password=settings.mysql.password,
        database=settings.mysql.database, charset="utf8mb4", autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT customer_id,risk_level_code,risk_level_name,risk_score,
                investment_experience,annual_income_range,total_assets,asset_allocation,
                product_preference,confidence_score,risk_flag,calibration_json
                FROM fin_customer_profile ORDER BY customer_id""")
            columns = [column[0] for column in cursor.description]
            customers = [dict(zip(columns, row)) for row in cursor.fetchall()]
            if not customers:
                raise RuntimeError("画像表为空，未执行清空")
            for customer in customers:
                normalized = normalize_risk_level(customer["risk_level_code"] or customer["risk_level_name"])
                customer["risk_level_code"] = normalized.risk_level_code
                customer["risk_level_name"] = normalized.risk_level_name
                score = int(customer["risk_score"] or _BAND_MIDPOINT[normalized.risk_level_code])
                customer["risk_score"] = score if is_score_compatible_with_risk_level(score, normalized) else _BAND_MIDPOINT[normalized.risk_level_code]
            if not apply:
                connection.rollback()
                return {"apply": False, "customers": len(customers), "target_tables": ["fin_customer_profile", "fin_risk_assessment"]}

            cursor.execute("DELETE FROM fin_risk_assessment")
            cursor.execute("DELETE FROM fin_customer_profile")
            for customer in customers:
                customer_id = customer["customer_id"]
                code = customer["risk_level_code"]
                name = customer["risk_level_name"]
                score = customer["risk_score"]
                basic, experience, risk_pref, behavior = _dimension_scores(score)
                profile_json = json.dumps({
                    "customer_id": customer_id,
                    "risk_level_code": code,
                    "risk_level_name": name,
                    "risk_score": score,
                    "dimensions": {"basic": {"score": basic}, "experience": {"score": experience}, "risk_pref": {"score": risk_pref}, "behavior": {"score": behavior}},
                }, ensure_ascii=False)
                cursor.execute(
                    """INSERT INTO fin_customer_profile
                    (customer_id,risk_level_code,risk_level_name,risk_score,investment_experience,
                     annual_income_range,total_assets,confidence_score,risk_flag,basic_score,
                     experience_score,risk_pref_score,behavior_score,profile_json,create_time,update_time)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,0.85,'normal',%s,%s,%s,%s,%s,NOW(),NOW())""",
                    (customer_id, code, name, score, customer["investment_experience"], customer["annual_income_range"], customer["total_assets"], basic, experience, risk_pref, behavior, profile_json),
                )
                cursor.execute(
                    """INSERT INTO fin_risk_assessment
                    (customer_id,assessment_date,total_score,risk_level,answers,assessor_type,valid_until,create_time)
                    VALUES (%s,%s,%s,%s,%s,'DEMO',%s,NOW())""",
                    (customer_id, date.today(), score, code, json.dumps({"source": "risk-level-reset"}), date.today() + timedelta(days=365)),
                )
        connection.commit()
        return {"apply": True, "customers": len(customers), "target_tables": ["fin_customer_profile", "fin_risk_assessment"]}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-reset-risk-profile-data", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.confirm_reset_risk_profile_data:
        parser.error("执行清空必须同时传入 --confirm-reset-risk-profile-data")
    print(json.dumps(reset(apply=args.apply), ensure_ascii=False))
