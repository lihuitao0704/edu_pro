import asyncio
import json

from app.utils.sse import stream_chat_result


def test_sse_done_event_preserves_the_final_structured_result():
    async def collect_events():
        return [event async for event in stream_chat_result({
            "session_id": "session-1",
            "reply": "已完成查询。",
            "agent": "customer_service",
            "confidence": 0.91,
            "data": {"recommendations": [{"product_name": "稳健债券A"}]},
        })]

    events = asyncio.run(collect_events())
    done = next(event for event in events if event["event"] == "done")
    payload = json.loads(done["data"])

    assert payload["reply"] == "已完成查询。"
    assert payload["agent"] == "customer_service"
    assert payload["data"]["recommendations"][0]["product_name"] == "稳健债券A"
