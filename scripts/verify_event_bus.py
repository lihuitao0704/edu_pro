"""Non-destructive live verification for Outbox -> Redis -> Agent consumer."""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import delete, select

from app.config.database import async_session_factory, close_redis, engine, get_redis
from app.model.entities import AgentEventConsumption, AgentEventOutbox
from app.service.agent_event_service import (
    AgentDomainEvent,
    EventDispatcher,
    EVENT_TRANSACTION_COMPLETED,
)


async def main() -> None:
    customer_id = 9_999_999_999
    event = AgentDomainEvent.create(
        event_type=EVENT_TRANSACTION_COMPLETED,
        source_agent="verification",
        customer_id=customer_id,
        correlation_id=f"event-bus-check:{uuid.uuid4()}",
        payload={
            "transaction_type": "verification",
            "transaction_no": "NON_BUSINESS_TEST",
            "amount": 0,
        },
    )
    profile_key = f"profile:{customer_id}"
    redis = await get_redis()

    try:
        subscriber_count = (await redis.pubsub_numsub("event:agent_domain"))[0][1]
        await redis.set(profile_key, "verification-sentinel", ex=60)

        async with async_session_factory() as db:
            await EventDispatcher.enqueue(db, event)
            await db.commit()

        status = None
        consumers: list[str] = []
        cache_cleared = False
        for _ in range(30):
            await asyncio.sleep(0.25)
            async with async_session_factory() as db:
                status = await db.scalar(
                    select(AgentEventOutbox.status).where(
                        AgentEventOutbox.event_id == event.event_id
                    )
                )
                consumers = list(
                    (
                        await db.scalars(
                            select(AgentEventConsumption.consumer).where(
                                AgentEventConsumption.event_id == event.event_id
                            )
                        )
                    ).all()
                )
            cache_cleared = not bool(await redis.exists(profile_key))
            if (
                status == "published"
                and "profile-cache-consumer" in consumers
                and cache_cleared
            ):
                break

        result = {
            "ok": (
                subscriber_count >= 4
                and status == "published"
                and consumers == ["profile-cache-consumer"]
                and cache_cleared
            ),
            "event_id": event.event_id,
            "domain_subscribers": subscriber_count,
            "outbox_status": status,
            "consumers": consumers,
            "profile_cache_cleared": cache_cleared,
        }
        print(json.dumps(result, ensure_ascii=False))
        if not result["ok"]:
            raise SystemExit(1)
    finally:
        await redis.delete(profile_key)
        async with async_session_factory() as db:
            await db.execute(
                delete(AgentEventConsumption).where(
                    AgentEventConsumption.event_id == event.event_id
                )
            )
            await db.execute(
                delete(AgentEventOutbox).where(
                    AgentEventOutbox.event_id == event.event_id
                )
            )
            await db.commit()
        await close_redis()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
