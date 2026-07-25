"""Canonical in-process domain events for the six-Agent collaboration layer."""

from __future__ import annotations

import inspect
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from typing import Awaitable, Callable


@dataclass(frozen=True)
class AgentDomainEvent:
    event_id: str
    event_type: str
    source_agent: str
    customer_id: int
    correlation_id: str
    payload: dict
    version: int = 1
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(
        cls,
        event_type: str,
        source_agent: str,
        customer_id: int,
        payload: dict,
        correlation_id: str | None = None,
    ) -> "AgentDomainEvent":
        if not event_type or not source_agent:
            raise ValueError("event_type and source_agent are required")
        if not isinstance(customer_id, int) or customer_id <= 0:
            raise ValueError("customer_id must be a positive integer")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            source_agent=source_agent,
            customer_id=customer_id,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload=payload,
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "version": self.version,
            "source_agent": self.source_agent,
            "customer_id": self.customer_id,
            "correlation_id": self.correlation_id,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentDomainEvent":
        return cls(
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
            source_agent=str(data["source_agent"]),
            customer_id=int(data["customer_id"]),
            correlation_id=str(data["correlation_id"]),
            payload=dict(data.get("payload") or {}),
            version=int(data.get("version", 1)),
            occurred_at=str(data["occurred_at"]),
        )


EventHandler = Callable[[AgentDomainEvent], Awaitable[None] | None]


class EventDispatcher:
    """In-process helper retained for unit-level handler dispatch."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[str, EventHandler]]] = defaultdict(list)
        self._consumed: set[tuple[str, str]] = set()

    def register(self, event_type: str, consumer: str, handler: EventHandler) -> None:
        self._handlers[event_type].append((consumer, handler))

    @staticmethod
    async def enqueue(db, event: AgentDomainEvent) -> None:
        """Write the event inside the caller's transaction for later publishing."""
        from app.model.entities import AgentEventOutbox

        db.add(
            AgentEventOutbox(
                event_id=event.event_id,
                event_type=event.event_type,
                source_agent=event.source_agent,
                customer_id=event.customer_id,
                correlation_id=event.correlation_id,
                payload={
                    "version": event.version,
                    "occurred_at": event.occurred_at,
                    "payload": event.payload,
                },
                status="pending",
            )
        )

    async def dispatch(self, event: AgentDomainEvent) -> None:
        for consumer, handler in self._handlers.get(event.event_type, []):
            key = (event.event_id, consumer)
            if key in self._consumed:
                continue
            self._consumed.add(key)
            outcome = handler(event)
            if inspect.isawaitable(outcome):
                await outcome


async def relay_outbox_once(batch_size: int = 100) -> int:
    """Publish committed outbox entries and retain failed entries for retry.

    Rows are claimed in a short database transaction before Redis is touched;
    a crashed relay is reclaimed after five minutes. This keeps publication
    strictly after the originating business transaction commits.
    """
    from app.config.database import async_session_factory
    from app.model.entities import AgentEventOutbox

    now = datetime.now()
    stale_before = now - timedelta(minutes=5)
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(AgentEventOutbox)
                .where(
                    (AgentEventOutbox.status == "pending")
                    | ((AgentEventOutbox.status == "publishing") & (AgentEventOutbox.claimed_at < stale_before))
                )
                .order_by(AgentEventOutbox.created_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for row in rows:
            row.status = "publishing"
            row.claimed_at = now
            row.retry_count += 1
        await db.commit()

    published = 0
    for row in rows:
        event = AgentDomainEvent(
            event_id=row.event_id,
            event_type=row.event_type,
            source_agent=row.source_agent,
            customer_id=row.customer_id,
            correlation_id=row.correlation_id,
            version=int((row.payload or {}).get("version", 1)),
            occurred_at=str((row.payload or {}).get("occurred_at")),
            payload=dict((row.payload or {}).get("payload") or {}),
        )
        from app.service.event_bus import publish_domain_event

        delivered = await publish_domain_event(event)
        async with async_session_factory() as db:
            record = await db.get(AgentEventOutbox, row.event_id, with_for_update=True)
            if not record:
                continue
            if delivered:
                record.status = "published"
                record.published_at = datetime.now()
                record.last_error = None
                published += 1
            else:
                record.status = "pending"
                record.last_error = "Redis publish failed; retained for retry"
            await db.commit()
    return published


async def run_outbox_relay(poll_seconds: float = 1.0) -> None:
    """Continuously relay committed six-Agent outbox records."""
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    while True:
        try:
            await relay_outbox_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Agent event outbox relay failed")
        await asyncio.sleep(poll_seconds)
