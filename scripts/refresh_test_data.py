"""Deterministic, offline factories for the guarded test-data refresh CLI.

This module deliberately has no database clients or configuration imports.  The
later refresh steps consume the generated rows after their own connection and
target checks have completed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5


TARGET_ROWS = 100
_BASE_TIME = datetime(2025, 1, 1, 9, 0, 0)
_PASSWORD_HASH = "$2b$12$4yrlZKix4Yp4mYxH4oAJxONmFRCvj6y9znBffvwSB3ikzJa/IgAha"
_RISK_LEVELS = ("C1", "C2", "C3", "C4", "C5")
_PRODUCT_RISKS = ("R1", "R2", "R3", "R4", "R5")
_INDUSTRIES = ("cash_management", "government_bond", "technology", "new_energy", "healthcare")


def _uuid(kind: str, index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"edu-pro-refresh/{kind}/{index}"))


def _timestamp(index: int) -> datetime:
    return _BASE_TIME + timedelta(days=index % 90, minutes=index)


def _customer_id(index: int) -> int:
    return index


def _product_id(index: int) -> int:
    return index


def _session_id(index: int) -> str:
    return f"refresh-session-{index:03d}"


def _trace_id(index: int) -> str:
    return f"refresh-trace-{_uuid('trace', index)}"


def _risk(index: int) -> str:
    return _RISK_LEVELS[(index - 1) % len(_RISK_LEVELS)]


def _product_risk(index: int) -> str:
    return _PRODUCT_RISKS[(index - 1) % len(_PRODUCT_RISKS)]


def _decimal(value: str) -> Decimal:
    return Decimal(value)


def mysql_table_inventory(connection) -> list[str]:
    """Return a stable inventory from an already-open MySQL connection."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE'")
        return sorted(row[0] for row in cursor.fetchall())


def build_dataset(target_rows: int = TARGET_ROWS) -> dict[str, list[dict]]:
    """Build a reproducible relational test dataset without touching a store."""
    if target_rows < 1:
        raise ValueError("target_rows must be positive")

    indexes = range(1, target_rows + 1)
    users = [
        {
            "id": _customer_id(index),
            "username": f"refresh_customer_{index:03d}",
            "password_hash": _PASSWORD_HASH,
            "user_type": "CUSTOMER",
            "employee_role": None,
            "customer_level": ("standard", "gold", "platinum", "private")[index % 4],
            "real_name": f"Refresh Customer {index:03d}",
            "phone": f"139{index:08d}",
            "id_card": f"110101199001{index:06d}",
            "email": f"refresh_customer_{index:03d}@example.test",
            "balance": _decimal(f"{100000 + index * 1000}.00"),
            "education": ("bachelor", "master", "college")[index % 3],
            "occupation": ("engineer", "teacher", "analyst", "designer")[index % 4],
            "age": 25 + index % 40,
            "id_card_expiry": date(2035, 1, 1) + timedelta(days=index),
            "status": "active",
            "create_time": _timestamp(index),
            "update_time": _timestamp(index),
        }
        for index in indexes
    ]
    products = [
        {
            "id": _product_id(index),
            "product_code": f"REFRESH-P{index:03d}",
            "product_name": f"Refresh Product {index:03d}",
            "product_type": ("fund", "bond", "wealth_management", "equity", "cash")[index % 5],
            "risk_level": _product_risk(index),
            "expected_return": _decimal(f"{2 + (index % 8) / 2:.4f}"),
            "min_amount": _decimal(f"{1000 * ((index % 10) + 1)}.00"),
            "term_days": (30, 90, 180, 365, 730)[index % 5],
            "fund_manager": f"Refresh Manager {index % 10:02d}",
            "industry": _INDUSTRIES[index % len(_INDUSTRIES)],
            "status": "active",
            "create_time": _timestamp(index),
            "update_time": _timestamp(index),
        }
        for index in indexes
    ]

    return {
        "sys_user": users,
        "fin_customer_profile": [
            {
                "id": index,
                "customer_id": _customer_id(index),
                "risk_level": _risk(index),
                "risk_score": 20 + (index % 5) * 16,
                "investment_experience": ("none", "limited", "experienced")[index % 3],
                "annual_income_range": ("100k-200k", "200k-500k", "500k-1m")[index % 3],
                "total_assets": _decimal(f"{200000 + index * 10000}.00"),
                "asset_allocation": {"cash": 0.2, "bond": 0.4, "equity": 0.4},
                "product_preference": {"risk": _product_risk(index), "industry": _INDUSTRIES[index % 5]},
                "confidence_score": _decimal("0.85"),
                "basic_score": _decimal("20.00"),
                "experience_score": _decimal("20.00"),
                "risk_pref_score": _decimal("30.00"),
                "behavior_score": _decimal("30.00"),
                "risk_flag": "normal",
                "profile_json": {"source": "refresh", "customer": index},
                "calibration_json": {"status": "aligned"},
                "create_time": _timestamp(index),
                "update_time": _timestamp(index),
            }
            for index in indexes
        ],
        "customer_tag": [
            {
                "id": index,
                "customer_id": _customer_id(index),
                "tag_name": "risk_preference",
                "tag_value": _risk(index),
                "source": "refresh_factory",
                "confidence": _decimal("0.90"),
                "valid_until": date(2026, 1, 1) + timedelta(days=index),
                "create_time": _timestamp(index),
                "update_time": _timestamp(index),
            }
            for index in indexes
        ],
        "risk_score_record": [
            {
                "id": index,
                "customer_id": _customer_id(index),
                "rating_date": _timestamp(index),
                "basic_score": _decimal("20.00"),
                "experience_score": _decimal("20.00"),
                "risk_pref_score": _decimal("30.00"),
                "behavior_score": _decimal("30.00"),
                "total_score": _decimal("80.00"),
                "risk_level": _risk(index),
                "detail_json": {"factory_index": index},
                "circuit_breakers": [],
                "trigger_type": "refresh_factory",
                "create_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_calibration_record": [
            {
                "id": index,
                "customer_id": _customer_id(index),
                "calibrate_time": _timestamp(index),
                "direction": "aligned",
                "self_reported": {"risk_level": _risk(index)},
                "behavioral": {"risk_level": _risk(index)},
                "triggered_rules": [],
                "summary": f"Refresh calibration {index:03d}",
                "trigger_type": "refresh_factory",
                "create_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_risk_assessment": [
            {
                "id": index,
                "customer_id": _customer_id(index),
                "assessment_date": date(2025, 1, 1) + timedelta(days=index),
                "total_score": 20 + (index % 5) * 16,
                "risk_level": _risk(index),
                "answers": {"q1": "refresh", "index": index},
                "assessor_type": "AI",
                "valid_until": date(2026, 1, 1) + timedelta(days=index),
                "create_time": _timestamp(index),
            }
            for index in indexes
        ],
        "risk_rule": [
            {
                "id": index,
                "rule_id": f"RF-{index:03d}",
                "rule_name": f"Refresh Rule {index:03d}",
                "rule_type": "scoring",
                "dimension": "risk_preference",
                "config_json": {"threshold": index},
                "weight": _decimal("1.00"),
                "is_active": True,
                "version": "refresh-1",
                "create_time": _timestamp(index),
                "update_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_risk_alert": [
            {
                "id": index,
                "customer_id": _customer_id(index),
                "alert_type": "large_transaction",
                "alert_level": ("low", "medium", "high")[index % 3],
                "trigger_detail": f"Refresh alert {index:03d}",
                "transaction_ids": {"transaction_no": f"REFRESH-T{index:03d}"},
                "status": "pending",
                "handler_id": _customer_id(index),
                "handle_result": None,
                "reminder_key": f"refresh-alert-{index:03d}",
                "create_time": _timestamp(index),
                "update_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_product": products,
        "fin_holdings": [
            {
                "id": index,
                "customer_id": _customer_id(index),
                "product_id": _product_id(index),
                "shares": _decimal(f"{1000 + index}.0000"),
                "cost_amount": _decimal(f"{10000 + index * 100}.00"),
                "current_value": _decimal(f"{10200 + index * 100}.00"),
                "profit_loss": _decimal("200.00"),
                "profit_ratio": _decimal("0.0200"),
                "status": "holding",
                "create_time": _timestamp(index),
                "update_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_transaction": [
            {
                "id": index,
                "transaction_no": f"REFRESH-T{index:03d}",
                "customer_id": _customer_id(index),
                "product_id": _product_id(index),
                "transaction_type": ("purchase", "redeem")[index % 2],
                "amount": _decimal(f"{10000 + index * 100}.00"),
                "shares": _decimal(f"{1000 + index}.0000"),
                "nav": _decimal("1.000000"),
                "fee": _decimal("5.00"),
                "status": "confirmed",
                "operator_id": _customer_id(index),
                "remark": f"Refresh transaction {index:03d}",
                "create_time": _timestamp(index),
                "update_time": _timestamp(index),
            }
            for index in indexes
        ],
        "biz_work_order": [
            {
                "id": index,
                "work_order_no": f"REFRESH-WO{index:03d}",
                "order_type": "consultation",
                "sub_type": "portfolio",
                "customer_id": _customer_id(index),
                "submitter_id": _customer_id(index),
                "handler_id": _customer_id(index),
                "current_node": "pending",
                "priority": "normal",
                "status": "pending",
                "biz_content": {"source": "refresh_factory"},
                "remark": f"Refresh work order {index:03d}",
                "create_time": _timestamp(index),
                "update_time": _timestamp(index),
            }
            for index in indexes
        ],
        "product_recommendation": [
            {
                "id": index,
                "customer_id": _customer_id(index),
                "session_id": _session_id(index),
                "product_code": f"REFRESH-P{index:03d}",
                "match_score": _decimal("90.00"),
                "score_detail": {"risk_match": True},
                "reasoning": f"Refresh recommendation {index:03d}",
                "status": "pending",
                "feedback_reason": None,
                "feedback_at": None,
                "create_time": _timestamp(index),
            }
            for index in indexes
        ],
        "agent_event_outbox": [
            {
                "event_id": _uuid("event", index),
                "event_type": "profile.updated",
                "source_agent": "profile",
                "customer_id": _customer_id(index),
                "correlation_id": _uuid("correlation", index),
                "payload": {"customer_id": index, "source": "refresh_factory"},
                "status": "published",
                "retry_count": 0,
                "created_at": _timestamp(index),
                "claimed_at": _timestamp(index),
                "published_at": _timestamp(index),
                "last_error": None,
            }
            for index in indexes
        ],
        "agent_event_consumption": [
            {
                "event_id": _uuid("event", index),
                "consumer": "risk_agent",
                "consumed_at": _timestamp(index),
            }
            for index in indexes
        ],
        "conversation_archive": [
            {
                "id": index,
                "session_id": _session_id(index),
                "user_id": _customer_id(index),
                "agent_type": "customer_service",
                "role": "assistant",
                "content": f"Refresh archived conversation {index:03d}",
                "tool_calls": [],
                "create_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_chat_session": [
            {
                "session_id": _session_id(index),
                "user_id": _customer_id(index),
                "status": "active",
                "summary": f"Refresh session {index:03d}",
                "last_intent": "product_recommendation",
                "last_agent": "advisor",
                "context_json": {"customer_id": index},
                "flagged": False,
                "create_time": _timestamp(index),
                "update_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_chat_message": [
            {
                "id": index,
                "session_id": _session_id(index),
                "user_id": _customer_id(index),
                "role": "user",
                "content": f"Refresh chat message {index:03d}",
                "intent": "product_recommendation",
                "agent_name": "advisor",
                "trace_id": _trace_id(index),
                "create_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_chat_entity": [
            {
                "id": index,
                "session_id": _session_id(index),
                "entity_type": "product",
                "entity_key": f"REFRESH-P{index:03d}",
                "entity_name": f"Refresh Product {index:03d}",
                "entity_id": str(_product_id(index)),
                "attributes_json": {"risk_level": _product_risk(index)},
                "confidence": _decimal("0.9500"),
                "last_seen_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_chat_feedback": [
            {
                "id": index,
                "session_id": _session_id(index),
                "user_id": _customer_id(index),
                "rating": 4 + index % 2,
                "comment": f"Refresh feedback {index:03d}",
                "intent": "product_recommendation",
                "agent_name": "advisor",
                "created_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_agent_trace": [
            {
                "trace_id": _trace_id(index),
                "session_id": _session_id(index),
                "user_id": _customer_id(index),
                "intent": "product_recommendation",
                "target_agent": "advisor",
                "status": "success",
                "input_masked": "refresh input",
                "output_masked": "refresh output",
                "total_latency_ms": 100 + index,
                "total_tokens": 200 + index,
                "created_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_agent_trace_span": [
            {
                "span_id": f"refresh-span-{_uuid('span', index)}",
                "trace_id": _trace_id(index),
                "parent_span_id": None,
                "span_type": "agent",
                "component_name": "advisor",
                "status": "success",
                "input_masked": "refresh input",
                "output_masked": "refresh output",
                "latency_ms": 100 + index,
                "token_input": 100,
                "token_output": 100,
                "created_time": _timestamp(index),
            }
            for index in indexes
        ],
        "fin_chat_metric_daily": [
            {
                "id": index,
                "metric_date": date(2025, 1, 1) + timedelta(days=index),
                "intent": "product_recommendation",
                "agent_name": "advisor",
                "session_count": 1,
                "turn_count": 1,
                "avg_rating": _decimal("4.50"),
                "fallback_rate": _decimal("0.0100"),
                "avg_response_ms": _decimal("120.00"),
            }
            for index in indexes
        ],
        "fin_knowledge_meta": [
            {
                "id": index,
                "knowledge_type": "product",
                "title": f"Refresh knowledge {index:03d}",
                "source_file": f"refresh_{index:03d}.md",
                "minio_path": f"refresh/knowledge/{index:03d}.md",
                "milvus_collection": "knowledge_base",
                "version": "refresh-1",
                "status": "active",
                "expire_at": None,
                "create_time": _timestamp(index),
                "update_time": _timestamp(index),
            }
            for index in indexes
        ],
    }
