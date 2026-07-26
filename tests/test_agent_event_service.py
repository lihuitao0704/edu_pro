import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.service.agent_event_service import (
    AgentDomainEvent,
    EventDispatcher,
    EVENT_RISK_ALERT_CREATED,
    EVENT_RISK_ALERT_RESOLVED,
    EVENT_TRANSACTION_COMPLETED,
)
from app.model.entities import ProductRecommendation
from app.service.event_bus import (
    EVENT_AGENT_DOMAIN,
    build_transaction_completed_event,
    publish_domain_event,
)
from app.service.risk_monitor_service import build_risk_alert_event
import app.service.event_bus as event_bus


def test_domain_event_has_required_correlation_fields():
    event = AgentDomainEvent.create(
        event_type="risk_alert_created",
        source_agent="risk",
        customer_id=27,
        payload={"alert_level": "high"},
        correlation_id="op-001",
    )

    assert event.event_id
    assert event.version == 1
    assert event.customer_id == 27
    assert event.correlation_id == "op-001"
    assert event.payload == {"alert_level": "high"}


def test_recommendation_model_keeps_feedback_lifecycle_fields():
    assert hasattr(ProductRecommendation, "status")
    assert hasattr(ProductRecommendation, "feedback_reason")
    assert hasattr(ProductRecommendation, "feedback_at")


def test_operation_event_uses_sender_as_transaction_customer():
    event = build_transaction_completed_event(
        action="transfer_funds",
        arguments={"from_customer_id": 27, "to_customer_id": 28, "amount": 1_000_000},
        result={"transaction_no": "TX-001"},
        operator_id=9,
        correlation_id="op-001",
    )

    assert event.event_type == EVENT_TRANSACTION_COMPLETED
    assert event.customer_id == 27
    assert event.payload["transaction_no"] == "TX-001"
    assert event.payload["transaction_type"] == "transfer_out"


def test_risk_alert_event_has_top_level_customer_identity():
    event = build_risk_alert_event(
        {
            "alert_id": 88,
            "customer_id": 27,
            "alert_level": "high",
            "trigger_rules": [{"rule_id": "R001"}],
            "summary": "大额现金交易",
        }
    )

    assert event.event_type == EVENT_RISK_ALERT_CREATED
    assert event.customer_id == 27
    assert event.payload["alert_level"] == "high"


class EventOutboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_persists_canonical_event_to_outbox(self):
        class FakeDb:
            def __init__(self):
                self.added = []

            def add(self, value):
                self.added.append(value)

        event = AgentDomainEvent.create(
            "analytics_insight", "analytics", 27, {"kind": "pnl_drawdown"}
        )
        db = FakeDb()

        await EventDispatcher.enqueue(db, event)

        self.assertEqual(event.event_id, db.added[0].event_id)
        self.assertEqual(27, db.added[0].customer_id)

    async def test_domain_event_is_published_on_single_domain_channel(self):
        event = AgentDomainEvent.create(
            "risk_alert_created", "risk", 27, {"alert_level": "high"}
        )
        with patch("app.service.event_bus.publish_event", new=AsyncMock()) as publish:
            await publish_domain_event(event)

        publish.assert_awaited_once_with(EVENT_AGENT_DOMAIN, event.to_dict(), event.correlation_id)

    async def test_risk_event_fans_out_to_three_independent_consumers(self):
        event = AgentDomainEvent.create(
            EVENT_RISK_ALERT_CREATED, "risk", 27, {"alert_level": "high", "alert_id": 88}
        )
        with patch(
            "app.service.event_bus._consume_profile_risk_event", new=AsyncMock()
        ) as profile, patch(
            "app.service.event_bus._consume_advisor_risk_event", new=AsyncMock()
        ) as advisor, patch(
            "app.service.event_bus._consume_customer_service_risk_event", new=AsyncMock()
        ) as customer:
            await event_bus.handle_domain_event(event)

        profile.assert_awaited_once_with(event)
        advisor.assert_awaited_once_with(event)
        customer.assert_awaited_once_with(event)

    async def test_suspicious_report_is_promoted_to_risk_alert(self):
        event = AgentDomainEvent.create(
            "suspicious_reported", "operator", 27, {"alert_id": 89, "reason": "异常资金流"}
        )
        with patch("app.service.event_bus.queue_domain_event", new=AsyncMock()) as publish:
            await event_bus.handle_domain_event(event)

        promoted = publish.await_args.args[0]
        self.assertEqual(EVENT_RISK_ALERT_CREATED, promoted.event_type)
        self.assertEqual(27, promoted.customer_id)
        self.assertEqual("medium", promoted.payload["alert_level"])

    async def test_expiring_assessment_updates_customer_context(self):
        event = AgentDomainEvent.create(
            "risk_assessment_expiring", "risk", 27, {"valid_until": "2026-08-01"}
        )
        with patch("app.service.event_bus._handle_c4_customer_context", new=AsyncMock()) as customer:
            await event_bus.handle_domain_event(event)

        customer.assert_awaited_once()
        self.assertEqual("risk_assessment_expiring", customer.await_args.args[0]["action"])

    async def test_duplicate_domain_delivery_is_filtered_by_durable_claim(self):
        event = AgentDomainEvent.create(
            EVENT_RISK_ALERT_CREATED, "risk", 27, {"alert_level": "high"}
        )
        envelope = {"payload": event.to_dict()}
        with patch(
            "app.service.event_bus.claim_domain_event_consumption",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.service.event_bus._consume_profile_risk_event", new=AsyncMock()
        ) as profile:
            await event_bus._handle_event(envelope, EVENT_AGENT_DOMAIN)

        profile.assert_not_awaited()

    async def test_resolved_alert_uses_same_three_consumer_pipeline(self):
        event = AgentDomainEvent.create(
            EVENT_RISK_ALERT_RESOLVED,
            "risk",
            27,
            {"alert_id": 88, "status": "resolved"},
        )
        with patch(
            "app.service.event_bus._consume_profile_risk_event", new=AsyncMock()
        ) as profile, patch(
            "app.service.event_bus._consume_advisor_risk_event", new=AsyncMock()
        ) as advisor, patch(
            "app.service.event_bus._consume_customer_service_risk_event", new=AsyncMock()
        ) as customer:
            await event_bus.handle_domain_event(event)

        profile.assert_awaited_once_with(event)
        advisor.assert_awaited_once_with(event)
        customer.assert_awaited_once_with(event)

    async def test_independent_subscriber_runs_only_its_owned_consumer(self):
        event = AgentDomainEvent.create(
            EVENT_RISK_ALERT_CREATED,
            "risk",
            27,
            {"alert_id": 88, "alert_level": "high"},
        )
        with patch(
            "app.service.event_bus.claim_domain_event_consumption",
            new=AsyncMock(return_value=True),
        ) as claim, patch(
            "app.service.event_bus._consume_profile_risk_event", new=AsyncMock()
        ) as profile, patch(
            "app.service.event_bus._consume_advisor_risk_event", new=AsyncMock()
        ) as advisor, patch(
            "app.service.event_bus._consume_customer_service_risk_event", new=AsyncMock()
        ) as customer:
            await event_bus.dispatch_domain_event(
                event,
                use_durable_claims=True,
                allowed_consumers={"advisor-risk-consumer"},
            )

        claim.assert_awaited_once_with(event.event_id, "advisor-risk-consumer")
        advisor.assert_awaited_once_with(event)
        profile.assert_not_awaited()
        customer.assert_not_awaited()

    async def test_resolved_alert_restores_profile_and_advisor_to_current_aggregate(self):
        event = AgentDomainEvent.create(
            EVENT_RISK_ALERT_RESOLVED,
            "risk",
            27,
            {"alert_id": 88, "status": "resolved"},
        )
        normal_state = {
            "risk_flag": "normal",
            "alert_level": None,
            "active_alert_count": 0,
            "latest_alert_id": None,
        }
        with patch(
            "app.service.event_bus._load_customer_risk_state",
            new=AsyncMock(return_value=normal_state),
        ), patch(
            "app.service.event_bus._set_profile_risk_flag", new=AsyncMock()
        ) as profile, patch(
            "app.service.event_bus._set_advisor_risk_flag", new=AsyncMock()
        ) as advisor:
            await event_bus._consume_profile_risk_event(event)
            await event_bus._consume_advisor_risk_event(event)

        profile.assert_awaited_once_with(27, "normal")
        advisor.assert_awaited_once_with(27, "normal")

    async def test_customer_context_is_removed_when_last_alert_is_resolved(self):
        event = AgentDomainEvent.create(
            EVENT_RISK_ALERT_RESOLVED,
            "risk",
            27,
            {"alert_id": 88, "status": "resolved"},
        )
        normal_state = {
            "risk_flag": "normal",
            "alert_level": None,
            "active_alert_count": 0,
            "latest_alert_id": None,
        }
        redis = SimpleNamespace(
            delete=AsyncMock(), srem=AsyncMock(), sadd=AsyncMock()
        )
        with patch(
            "app.config.database.get_redis", new=AsyncMock(return_value=redis)
        ), patch(
            "app.service.event_bus._load_customer_risk_state",
            new=AsyncMock(return_value=normal_state),
        ):
            await event_bus._consume_customer_service_risk_event(event)

        redis.delete.assert_awaited_once_with("cs_risk_ctx:27")
        redis.srem.assert_awaited_once_with("risk:alert:pending", "88")

    async def test_failed_logical_consumer_releases_claim_and_requeues_outbox(self):
        event = AgentDomainEvent.create(
            EVENT_RISK_ALERT_CREATED,
            "risk",
            27,
            {"alert_id": 88, "alert_level": "high"},
        )
        with patch(
            "app.service.event_bus.claim_domain_event_consumption",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.service.event_bus._consume_profile_risk_event",
            new=AsyncMock(side_effect=RuntimeError("db unavailable")),
        ), patch(
            "app.service.event_bus.release_domain_event_consumption",
            new=AsyncMock(),
        ) as release, patch(
            "app.service.agent_event_service.mark_outbox_for_retry",
            new=AsyncMock(),
        ) as retry:
            with self.assertRaises(RuntimeError):
                await event_bus.dispatch_domain_event(event, use_durable_claims=True)

        release.assert_awaited_once_with(event.event_id, "profile-risk-consumer")
        retry.assert_awaited_once()


class EventDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatcher_delivers_one_event_once_per_consumer(self):
        dispatcher = EventDispatcher()
        delivered = []

        async def profile_consumer(event):
            delivered.append(("profile", event.customer_id))

        async def advisor_consumer(event):
            delivered.append(("advisor", event.payload["alert_level"]))

        dispatcher.register("risk_alert_created", "profile", profile_consumer)
        dispatcher.register("risk_alert_created", "advisor", advisor_consumer)
        event = AgentDomainEvent.create(
            event_type="risk_alert_created",
            source_agent="risk",
            customer_id=27,
            payload={"alert_level": "high"},
        )

        await dispatcher.dispatch(event)
        await dispatcher.dispatch(event)

        self.assertEqual([("profile", 27), ("advisor", "high")], delivered)
