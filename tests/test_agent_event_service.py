import unittest

from app.service.agent_event_service import AgentDomainEvent, EventDispatcher
from app.model.entities import ProductRecommendation


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
