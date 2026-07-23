"""Server-Sent Events formatting for chat responses."""

import json
from collections.abc import AsyncIterator


async def stream_chat_result(
    result: dict, chunk_size: int = 50
) -> AsyncIterator[dict[str, str]]:
    session_id = str(result.get("session_id") or "")
    meta = {
        "session_id": session_id,
        "intent": result.get("intent", ""),
        "confidence": result.get("confidence", 0),
        "agent_type": result.get("agent_type", ""),
    }
    yield {"event": "meta", "data": json.dumps(meta, ensure_ascii=False)}

    reply = str(result.get("reply") or "")
    size = max(int(chunk_size), 1)
    for offset in range(0, len(reply), size):
        yield {
            "event": "delta",
            "data": json.dumps(
                {"content": reply[offset : offset + size]}, ensure_ascii=False
            ),
        }

    sources = result.get("sources") or []
    if sources:
        yield {
            "event": "sources",
            "data": json.dumps({"sources": sources}, ensure_ascii=False, default=str),
        }

    yield {
        "event": "done",
        "data": json.dumps({"session_id": session_id}, ensure_ascii=False),
    }
