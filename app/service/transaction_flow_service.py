"""Shared transaction → risk alert → work-order orchestration."""

from typing import Optional
from sqlalchemy import text

from app.engine.confidence import ConfidenceCalculator
from app.service.risk_monitor_service import RiskMonitorService


class TransactionFlowService:
    def __init__(
        self,
        monitor: Optional[RiskMonitorService] = None,
        confidence: Optional[ConfidenceCalculator] = None,
    ):
        self.monitor_engine = monitor or RiskMonitorService()
        self.confidence = confidence or ConfidenceCalculator()

    @staticmethod
    def derive_context(event: dict, customer: dict, stats: dict) -> dict:
        """Fill missing AML context while preserving explicit event evidence."""
        derived = {
            **{key: value for key, value in customer.items() if value is not None},
            **{key: value for key, value in stats.items() if value is not None},
        }
        return {
            **derived,
            **{key: value for key, value in event.items() if value is not None},
        }

    async def enrich_context(self, db, event: dict) -> dict:
        customer_result = await db.execute(
            text(
                "SELECT u.age, "
                "TIMESTAMPDIFF(DAY, u.create_time, NOW()) AS account_age_days, "
                "p.annual_income_range "
                "FROM sys_user u "
                "LEFT JOIN fin_customer_profile p ON p.customer_id = u.id "
                "WHERE u.id = :customer_id"
            ),
            {"customer_id": event["customer_id"]},
        )
        customer_row = customer_result.mappings().first() or {}
        customer = dict(customer_row)
        customer["annual_income"] = _income_range_to_amount(
            customer.pop("annual_income_range", None)
        )

        stats_result = await db.execute(
            text(
                "SELECT "
                "SUM(CASE WHEN create_time >= DATE_SUB(NOW(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS weekly_count, "
                "COALESCE(SUM(CASE WHEN create_time >= DATE_SUB(NOW(), INTERVAL 7 DAY) THEN amount ELSE 0 END), 0) AS weekly_total, "
                "COALESCE(SUM(CASE WHEN DATE(create_time) = CURDATE() THEN amount ELSE 0 END), 0) AS daily_amount, "
                "SUM(CASE WHEN create_time >= DATE_SUB(NOW(), INTERVAL 30 DAY) AND transaction_type IN ('purchase','申购') THEN 1 ELSE 0 END) AS buy_count_30d, "
                "SUM(CASE WHEN create_time >= DATE_SUB(NOW(), INTERVAL 30 DAY) AND transaction_type IN ('redeem','赎回') THEN 1 ELSE 0 END) AS sell_count_30d, "
                "COALESCE(SUM(CASE WHEN create_time >= DATE_SUB(NOW(), INTERVAL 365 DAY) THEN amount ELSE 0 END), 0) / 12 AS monthly_avg_12m, "
                "COALESCE(SUM(amount), 0) AS total_since_open "
                "FROM fin_transaction WHERE customer_id = :customer_id"
            ),
            {"customer_id": event["customer_id"]},
        )
        stats = dict(stats_result.mappings().first() or {})
        return self.derive_context(event, customer, stats)

    async def monitor(self, db, event: dict) -> dict:
        payload = await self.enrich_context(db, event)
        triggered = self.monitor_engine.evaluate_all(payload)
        if not triggered:
            return {"alert": None, "triggered_count": 0}

        _, history = await self.monitor_engine.get_alerts(
            db, customer_id=payload["customer_id"]
        )
        level = self.monitor_engine.grade(triggered, history, payload)
        confidence = self.confidence.calc_single(
            source="ai_extract", evidence_count=len(triggered)
        )
        alert = self.monitor_engine.build_alert(
            payload, triggered, level, confidence
        )
        alert_id = await self.monitor_engine.save_alert(db, alert)
        alert["alert_id"] = alert_id
        return {"alert": alert, "triggered_count": len(triggered)}


def _income_range_to_amount(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    normalized = value.replace("万元", "万").replace("以上", "+")
    ranges = {
        "10万以下": 100_000,
        "10-30万": 300_000,
        "30-50万": 500_000,
        "50-100万": 1_000_000,
        "100-300万": 3_000_000,
        "300万+": 3_000_000,
    }
    return float(ranges.get(normalized, 0)) or None
