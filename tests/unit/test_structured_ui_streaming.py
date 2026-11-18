"""Native parts share generation replay, stop/save and HTTP compatibility boundaries."""

import asyncio
import json
import unittest
from unittest.mock import patch

from starlette.responses import JSONResponse, StreamingResponse

from services.chat_generation import clear_generation_job_state, start_generation_job
from services.structured_ui_delivery import StructuredUiDeliveryMiddleware
from tests.unit.test_chat_streaming import _direct_answer_stream
from tests.unit.test_structured_ui import document, fence


class StructuredUiGenerationTests(unittest.TestCase):
    def tearDown(self):
        clear_generation_job_state()

    def test_generation_saves_once_replays_ids_and_never_streams_raw_json(self):
        persisted = []
        source = "Before\n" + fence() + "After"
        with patch("services.chat_generation_llm_stream.get_llm_response_stream", return_value=_direct_answer_stream(*source)):
            job = start_generation_job(
                "guest:issue870:stream",
                conversation_messages=[{"role": "user", "content": "比較して"}],
                model="openai/gpt-oss-120b",
                ui_mode="STRUCTURED_UI",
                persist_response=lambda response, **kwargs: persisted.append((response, kwargs)),
            )
            events = list(job.iter_events(heartbeat_seconds=0.01))
        events = [event for event in events if event]
        self.assertEqual(events[-1].event, "done")
        self.assertEqual(len(persisted), 1)
        streamed = "".join(event.payload.get("text", "") for event in events if event.event in {"chunk", "answer_draft"})
        self.assertNotIn('"root_id"', streamed)
        self.assertNotIn("chatcore-ui", streamed)
        self.assertEqual([part["type"] for part in persisted[0][1]["message_parts"]], ["text", "structured_ui", "text"])
        replay = [event for event in job.iter_events(after_sequence_id=events[-2].sequence_id) if event]
        self.assertEqual([(event.sequence_id, event.event) for event in replay], [(events[-1].sequence_id, "done")])
        self.assertEqual(job._telemetry.structured_ui_blocks, 1)
        self.assertIsNotNone(job._telemetry.first_visible_ui_ms)

    def test_stopped_partial_block_is_hidden_and_not_repaired(self):
        # The cancel path uses the same normalizer, without calling the repair model.
        from services.chat_generation import ChatGenerationJob

        job = ChatGenerationJob(
            conversation_messages=[{"role": "user", "content": "比較して"}],
            model="openai/gpt-oss-120b",
            ui_mode="STRUCTURED_UI",
            persist_response=lambda *_args, **_kwargs: None,
        )
        job._chunks[:] = ["Before\n" + fence() + '```chatcore-ui\n{"version":']
        with patch("services.chat_generation_finalization.get_llm_response") as llm:
            job.cancel()
        self.assertNotIn('"version"', job.response)
        self.assertNotIn("chatcore-ui", job.response)
        llm.assert_not_called()


class StructuredUiDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, capable, streaming=False):
        part = {"type": "structured_ui", "ui": document()}
        payload = {"response": "fallback", "parts": [{"type": "text", "text": "before"}, part]}

        async def app(scope, receive, send):
            if streaming:

                async def chunks():
                    raw = b"id: 7\nevent: response_parts_updated\ndata: " + json.dumps(payload).encode() + b"\n\n"
                    yield raw[:47]
                    yield raw[47:]

                response = StreamingResponse(chunks(), media_type="text/event-stream")
            else:
                response = JSONResponse(payload)
            await response(scope, receive, send)

        sent = []
        headers = [(b"x-chatcore-ui-version", b"1")] if capable else []
        scope = {"type": "http", "method": "GET", "path": "/api/get_chat_history", "headers": headers, "asgi": {"spec_version": "2.4"}}

        async def receive():
            await asyncio.sleep(100)

        async def send(message):
            sent.append(message)

        await StructuredUiDeliveryMiddleware(app)(scope, receive, send)
        body = b"".join(message.get("body", b"") for message in sent)
        return sent, body

    async def test_legacy_json_flattens_and_updates_length(self):
        sent, body = await self.request(False)
        self.assertEqual(json.loads(body)["parts"][1], {"type": "text", "text": document()["fallback_text"]})
        self.assertEqual(dict(sent[0]["headers"])[b"content-length"], str(len(body)).encode())
        self.assertIn(b"X-ChatCore-UI-Version", dict(sent[0]["headers"])[b"vary"])

    async def test_capable_clients_keep_native_parts(self):
        _, body = await self.request(True)
        self.assertEqual(json.loads(body)["parts"][1]["type"], "structured_ui")

    async def test_split_sse_frames_keep_sequence_and_fallback(self):
        _, body = await self.request(False, streaming=True)
        self.assertIn(b"id: 7\n", body)
        self.assertNotIn(b'"structured_ui"', body)
        self.assertIn(b'"text": "A: 10, B: 20"', body)
