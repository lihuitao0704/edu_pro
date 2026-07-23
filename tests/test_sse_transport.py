import json
import unittest


class SSETransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_events_are_ordered_and_terminate_with_done(self):
        from app.utils.sse import stream_chat_result

        result = {
            "reply": "稳健配置建议",
            "sources": [{"title": "产品手册"}],
            "session_id": "sse-1",
            "intent": "product_inquiry",
            "confidence": 0.9,
        }

        events = [event async for event in stream_chat_result(result, chunk_size=2)]

        self.assertEqual("meta", events[0]["event"])
        self.assertEqual("done", events[-1]["event"])
        self.assertTrue(any(event["event"] == "delta" for event in events))
        self.assertTrue(any(event["event"] == "sources" for event in events))
        done = json.loads(events[-1]["data"])
        self.assertEqual("sse-1", done["session_id"])

    async def test_unicode_chunks_reconstruct_original_reply(self):
        from app.utils.sse import stream_chat_result

        reply = "客户画像：稳健型。"
        events = [
            event
            async for event in stream_chat_result(
                {"reply": reply, "session_id": "sse-2"}, chunk_size=3
            )
        ]
        reconstructed = "".join(
            json.loads(event["data"])["content"]
            for event in events
            if event["event"] == "delta"
        )

        self.assertEqual(reply, reconstructed)


if __name__ == "__main__":
    unittest.main()
