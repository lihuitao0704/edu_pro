import unittest
from unittest.mock import AsyncMock
from types import SimpleNamespace
from unittest.mock import patch

from app.model.schemas import TransactionEvent


class TransactionEventTests(unittest.TestCase):
    def test_extended_aml_context_is_preserved(self):
        event = TransactionEvent(
            customer_id=5,
            transaction_id="TX-RISK-001",
            amount=199_999,
            transaction_type="transfer_out",
            timestamp="2026-07-23T01:15:00",
            weekly_count=25,
            weekly_total=320_000,
            age=70,
            monthly_avg_12m=20_000,
            counterparty={"country": "伊朗"},
        )

        payload = event.model_dump()

        self.assertEqual(25, payload["weekly_count"])
        self.assertEqual(320_000, payload["weekly_total"])
        self.assertEqual(70, payload["age"])


class _Rule:
    rule_id = "R001"
    rule_name = "大额现金交易"
    risk_level = "中"


class _FakeMonitor:
    def __init__(self):
        self.saved = None

    def evaluate_all(self, event):
        return [_Rule()]

    async def get_alerts(self, db, **kwargs):
        return 0, []

    def grade(self, triggered, history, event):
        return "low"

    def build_alert(self, event, triggered, level, confidence):
        return {
            "customer_id": event["customer_id"],
            "transaction_id": event["transaction_id"],
            "alert_level": level,
            "trigger_rules": [{"rule_id": "R001"}],
            "confidence": confidence,
            "summary": "风险交易",
            "recommendation": "关注",
            "status": "pending",
        }

    async def save_alert(self, db, alert):
        self.saved = alert
        return 88


class TransactionFlowTests(unittest.IsolatedAsyncioTestCase):
    def test_derived_context_fills_history_without_overwriting_explicit_values(self):
        from app.service.transaction_flow_service import TransactionFlowService

        result = TransactionFlowService.derive_context(
            event={
                "customer_id": 5,
                "amount": 120_000,
                "age": 72,
                "weekly_count": 99,
            },
            customer={"age": 68, "annual_income": 300_000, "account_age_days": 20},
            stats={
                "weekly_count": 8,
                "weekly_total": 180_000,
                "monthly_avg_12m": 30_000,
            },
        )

        self.assertEqual(72, result["age"])
        self.assertEqual(99, result["weekly_count"])
        self.assertEqual(300_000, result["annual_income"])
        self.assertEqual(30_000, result["monthly_avg_12m"])

    async def test_monitor_returns_persisted_alert_and_count(self):
        from app.service.transaction_flow_service import TransactionFlowService

        monitor = _FakeMonitor()
        service = TransactionFlowService(monitor=monitor)

        event = {
            "customer_id": 5,
            "transaction_id": "TX-RISK-001",
            "amount": 100_000,
            "transaction_type": "cash",
            "timestamp": "2026-07-23T12:00:00",
        }
        service.enrich_context = AsyncMock(return_value=event)

        result = await service.monitor(db=object(), event=event)

        self.assertEqual(1, result["triggered_count"])
        self.assertEqual(88, result["alert"]["alert_id"])
        self.assertEqual("low", result["alert"]["alert_level"])

    async def test_monitor_returns_empty_result_for_normal_transaction(self):
        from app.service.transaction_flow_service import TransactionFlowService

        monitor = _FakeMonitor()
        monitor.evaluate_all = lambda event: []
        service = TransactionFlowService(monitor=monitor)

        event = {
            "customer_id": 3,
            "transaction_id": "TX-NORMAL",
            "amount": 1_000,
            "transaction_type": "purchase",
            "timestamp": "2026-07-23T12:00:00",
        }
        service.enrich_context = AsyncMock(return_value=event)

        result = await service.monitor(db=object(), event=event)

        self.assertEqual({"alert": None, "triggered_count": 0}, result)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _HandleDb:
    def __init__(self, alert, work_order):
        self.results = [_ScalarResult(alert), _ScalarResult(work_order)]
        self.flush = AsyncMock()

    async def execute(self, *args, **kwargs):
        return self.results.pop(0)


class AlertResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolving_alert_closes_work_order_and_pending_marker(self):
        from app.service.risk_monitor_service import RiskMonitorService

        alert = SimpleNamespace(
            id=88,
            customer_id=5,
            alert_level="medium",
            transaction_ids={"trigger_rules": []},
            trigger_detail="risk",
            status="未处理",
            handler_id=None,
            handle_result=None,
            create_time=None,
            update_time=None,
        )
        work_order = SimpleNamespace(status="处理中", current_node="待处理")
        db = _HandleDb(alert, work_order)
        redis = SimpleNamespace(srem=AsyncMock())

        with patch(
            "app.config.database.get_redis",
            new=AsyncMock(return_value=redis),
        ):
            result = await RiskMonitorService().handle_alert(
                db, "88", "resolved", 2, "已核实"
            )

        self.assertEqual("resolved", result["status"])
        self.assertEqual("已完成", work_order.status)
        self.assertEqual("已关闭", work_order.current_node)
        redis.srem.assert_awaited_once_with("risk:alert:pending", "88")


class WorkOrderClosureTests(unittest.IsolatedAsyncioTestCase):
    async def test_closing_linked_work_order_resolves_alert_with_jwt_actor(self):
        from app.api.operations.workorder import handle_work_order

        detail_result = SimpleNamespace(
            mappings=lambda: SimpleNamespace(
                first=lambda: {"biz_content": {"alert_id": 42}}
            )
        )
        update_result = SimpleNamespace(rowcount=1)
        db = AsyncMock()
        db.execute.side_effect = [detail_result, update_result]

        with patch(
            "app.api.operations.workorder.RiskMonitorService.handle_alert",
            new=AsyncMock(return_value={"alert_id": "42", "status": "resolved"}),
        ) as handle_alert:
            response = await handle_work_order(
                7,
                {"status": "已完成", "handler_id": 999, "handle_note": "核实完成"},
                db=db,
                user={"user_id": 9, "role": "风控专员"},
            )

        handle_alert.assert_awaited_once_with(
            db, "42", "resolved", 9, "核实完成"
        )
        self.assertEqual(200, response["code"])


if __name__ == "__main__":
    unittest.main()
