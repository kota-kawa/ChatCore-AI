import asyncio
import json
import threading
import unittest
from unittest.mock import patch

from starlette.responses import StreamingResponse

from blueprints.chat.messages import (
    _paginate_ephemeral_chat_history,
    _truncate_conversation_for_llm,
    chat,
    _iter_llm_stream_events,
    chat_generation_status,
    chat_generation_stream,
    get_chat_history,
)
from services.chat_contract import CHAT_HISTORY_PAGE_SIZE_DEFAULT
from services.chat_generation import (
    ChatGenerationAlreadyRunningError,
    ChatGenerationService,
    build_generation_key,
    clear_generation_job_state,
    has_active_generation,
    start_generation_job,
)
from services.llm import LlmConfigurationError
from tests.helpers.request_helpers import build_request


class _FakeRedisPipeline:
    def __init__(self, redis_client):
        self._redis = redis_client
        self._commands = []

    def rpush(self, key, value):
        self._commands.append(("rpush", key, value))
        return self

    def expire(self, key, ttl):
        self._commands.append(("expire", key, ttl))
        return self

    def publish(self, channel, message):
        self._commands.append(("publish", channel, message))
        return self

    def execute(self):
        for command, key, value in self._commands:
            getattr(self._redis, command)(key, value)
        self._commands.clear()
        return True


class _FakeRedis:
    def __init__(self):
        self._values = {}
        self._lists = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._values:
            return False
        self._values[key] = value
        return True

    def exists(self, key):
        if key in self._values:
            return 1
        if key in self._lists and len(self._lists[key]) > 0:
            return 1
        return 0

    def lrange(self, key, start, end):
        values = list(self._lists.get(key, []))
        if not values:
            return []
        if end < 0:
            end = len(values) - 1
        return values[start : end + 1]

    def rpush(self, key, value):
        self._lists.setdefault(key, []).append(value)
        return len(self._lists[key])

    def expire(self, key, ttl):
        return True

    def publish(self, channel, message):
        return 1

    def pipeline(self):
        return _FakeRedisPipeline(self)

    def eval(self, *_args, **_kwargs):
        return 1


class _SilentPubSub:
    def __init__(self):
        self.channels = []
        self.closed = False

    def subscribe(self, channel):
        self.channels.append(channel)

    def get_message(self, timeout=0.0):
        return None

    def close(self):
        self.closed = True


class _FakeRedisWithPubSub(_FakeRedis):
    def __init__(self):
        super().__init__()
        self.pubsub_instance = _SilentPubSub()

    def pubsub(self, ignore_subscribe_messages=True):
        return self.pubsub_instance


def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/chat",
        json_body=json_body,
        session=session,
    )


class ChatStreamingTestCase(unittest.TestCase):
    def setUp(self):
        clear_generation_job_state(cancel_running=True)

    def tearDown(self):
        clear_generation_job_state(cancel_running=True)

    def test_truncate_conversation_for_llm_keeps_system_and_recent_history(self):
        messages = [{"role": "system", "content": "system"}]
        for index in range(60):
            role = "user" if index % 2 == 0 else "assistant"
            messages.append({"role": role, "content": f"msg-{index}"})

        truncated = _truncate_conversation_for_llm(messages)

        self.assertEqual(truncated[0]["role"], "system")
        self.assertLessEqual(len(truncated), 41)
        self.assertEqual(truncated[-1]["content"], "msg-59")

    def test_paginate_ephemeral_chat_history_reports_has_more_and_cursor(self):
        rows = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"msg-{index}"}
            for index in range(5)
        ]

        payload = _paginate_ephemeral_chat_history(rows, limit=2)

        self.assertEqual(
            [message["id"] for message in payload["messages"]],
            [4, 5],
        )
        self.assertTrue(payload["pagination"]["has_more"])
        self.assertEqual(payload["pagination"]["next_before_id"], 4)

    def test_paginate_ephemeral_chat_history_respects_before_id_cursor(self):
        rows = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"msg-{index}"}
            for index in range(5)
        ]

        payload = _paginate_ephemeral_chat_history(rows, limit=2, before_message_id=4)

        self.assertEqual(
            [message["id"] for message in payload["messages"]],
            [2, 3],
        )
        self.assertTrue(payload["pagination"]["has_more"])
        self.assertEqual(payload["pagination"]["next_before_id"], 2)

    def test_chat_returns_streaming_response_for_gemini(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "gemini-2.5-flash"},
            session={},
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch(
                        "blueprints.chat.messages.ephemeral_store.get_messages",
                        return_value=[{"role": "user", "content": "こんにちは"}],
                    ):
                        with patch("blueprints.chat.messages.ephemeral_store.append_message"):
                            with patch(
                                "blueprints.chat.messages.consume_llm_daily_quota",
                                return_value=(True, 1, 300),
                            ):
                                response = asyncio.run(chat(request))

        self.assertIsInstance(response, StreamingResponse)
        self.assertEqual(response.media_type, "text/event-stream")

    def test_chat_returns_streaming_response_for_groq(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "openai/gpt-oss-120b"},
            session={},
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch(
                        "blueprints.chat.messages.ephemeral_store.get_messages",
                        return_value=[{"role": "user", "content": "こんにちは"}],
                    ):
                        with patch("blueprints.chat.messages.ephemeral_store.append_message"):
                            with patch(
                                "blueprints.chat.messages.consume_llm_daily_quota",
                                return_value=(True, 1, 300),
                            ):
                                response = asyncio.run(chat(request))

        self.assertIsInstance(response, StreamingResponse)
        self.assertEqual(response.media_type, "text/event-stream")

    def test_chat_rejects_invalid_model_before_persisting_authenticated_message(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "room-auth", "model": "invalid-model"},
            session={"user_id": 42},
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                with patch("blueprints.chat.messages.save_message_to_db") as mock_save_message:
                    with patch(
                        "blueprints.chat.messages.get_chat_room_messages",
                        return_value=[{"role": "user", "content": "こんにちは"}],
                    ):
                        with patch(
                            "blueprints.chat.messages.delete_chat_room_if_no_assistant_messages",
                            return_value=True,
                        ) as mock_delete_room:
                            response = asyncio.run(chat(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid-model", payload["error"])
        mock_save_message.assert_not_called()
        mock_delete_room.assert_not_called()

    def test_streaming_generation_error_discards_guest_room_without_assistant_reply(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "room-guest", "model": "gemini-2.5-flash"},
            session={},
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.get_session_id", return_value="sid-1"):
                    with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                        with patch(
                            "blueprints.chat.messages.ephemeral_store.get_messages",
                            return_value=[{"role": "user", "content": "こんにちは"}],
                        ):
                            with patch("blueprints.chat.messages.ephemeral_store.append_message"):
                                with patch(
                                    "blueprints.chat.messages.consume_llm_daily_quota",
                                    return_value=(True, 1, 300),
                                ):
                                    with patch(
                                        "services.chat_generation.get_llm_response_stream",
                                        side_effect=LlmConfigurationError(
                                            "OPENAI_API_KEY が未設定です。"
                                        ),
                                    ):
                                        with patch(
                                            "blueprints.chat.messages.ephemeral_store.delete_room_if_no_assistant_messages",
                                            return_value=True,
                                        ) as mock_delete_room:
                                            response = asyncio.run(chat(request))

                                            async def _consume():
                                                chunks = []
                                                async for chunk in response.body_iterator:
                                                    chunks.append(chunk)
                                                return b"".join(chunks)

                                            body = asyncio.run(_consume()).decode("utf-8")

        self.assertIsInstance(response, StreamingResponse)
        self.assertIn("event: error", body)
        self.assertIn("OPENAI_API_KEY が未設定です。", body)
        mock_delete_room.assert_called_once_with("sid-1", "room-guest")

    def test_background_generation_job_persists_final_reply_for_guest(self):
        persisted_messages = []

        with patch(
            "services.chat_generation.get_llm_response_stream",
            return_value=iter(["こん", "にちは"]),
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "こんにちは"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(
                    ("sid-1", "default", "assistant", response)
                ),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: chunk", body)
        self.assertIn('"text": "こん"', body)
        self.assertIn("event: done", body)
        self.assertIn('"response": "こんにちは"', body)
        self.assertEqual(
            persisted_messages,
            [("sid-1", "default", "assistant", "こんにちは")],
        )

    def test_background_generation_job_surfaces_configuration_error_message(self):
        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=LlmConfigurationError("OPENAI_API_KEY が未設定です。"),
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "こんにちは"}],
                model="gpt-5-mini-2025-08-07",
                persist_response=lambda _: None,
            )
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: error", body)
        self.assertIn("OPENAI_API_KEY が未設定です。", body)

    def test_has_active_generation_is_false_after_job_completion(self):
        release_generation = threading.Event()

        def delayed_stream(*_args, **_kwargs):
            release_generation.wait(timeout=1.0)
            yield "ok"

        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=delayed_stream,
        ):
            job_key = build_generation_key(chat_room_id="default", user_id=1)
            job = start_generation_job(
                job_key,
                conversation_messages=[{"role": "user", "content": "こんにちは"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda _: None,
            )

            self.assertTrue(has_active_generation(job_key))
            release_generation.set()
            self.assertTrue(job.wait(timeout=1.0))
            self.assertFalse(has_active_generation(job_key))

    def test_start_generation_job_rejects_duplicate_active_job(self):
        release_generation = threading.Event()

        def delayed_stream(*_args, **_kwargs):
            release_generation.wait(timeout=1.0)
            yield "done"

        with patch("services.chat_generation.get_llm_response_stream", side_effect=delayed_stream):
            job_key = build_generation_key(chat_room_id="default", user_id=7)
            start_generation_job(
                job_key,
                conversation_messages=[{"role": "user", "content": "こんにちは"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda _: None,
            )

            with self.assertRaises(ChatGenerationAlreadyRunningError):
                start_generation_job(
                    job_key,
                    conversation_messages=[{"role": "user", "content": "再送"}],
                    model="openai/gpt-oss-120b",
                    persist_response=lambda _: None,
                )

            release_generation.set()

    def test_generation_continues_after_disconnect_and_reopen_returns_completed_reply(self):
        stored_messages = []
        release_generation = threading.Event()
        generation_finished = threading.Event()
        session = {"user_id": 42}

        def save_message(room_id, message, sender):
            stored_messages.append((room_id, message, sender))
            if sender == "assistant":
                generation_finished.set()

        def get_messages(room_id):
            return [
                {
                    "role": "user" if sender == "user" else "assistant",
                    "content": message,
                }
                for stored_room_id, message, sender in stored_messages
                if stored_room_id == room_id
            ]

        def fetch_history(room_id, limit, before_message_id=None):
            messages = [
                {
                    "id": index + 1,
                    "message": message,
                    "sender": sender,
                    "timestamp": "2026-03-17T00:00:00",
                }
                for index, (stored_room_id, message, sender) in enumerate(stored_messages)
                if stored_room_id == room_id
            ]
            return {
                "messages": messages[-limit:],
                "pagination": {
                    "limit": limit,
                    "has_more": False,
                    "next_before_id": None,
                },
            }

        def delayed_stream(*_args, **_kwargs):
            yield "完"
            release_generation.wait(timeout=1.0)
            yield "了"

        request = make_request(
            {"message": "こんにちは", "chat_room_id": "room-1", "model": "openai/gpt-oss-120b"},
            session=session,
        )

        with (
            patch("blueprints.chat.messages.cleanup_ephemeral_chats"),
            patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)),
            patch("blueprints.chat.messages.save_message_to_db", side_effect=save_message),
            patch("blueprints.chat.messages.get_chat_room_messages", side_effect=get_messages),
            patch("blueprints.chat.messages._fetch_chat_history", side_effect=fetch_history),
            patch("blueprints.chat.messages.get_user_by_id", return_value={}),
            patch("blueprints.chat.messages.get_room_summary", return_value={}),
            patch("blueprints.chat.messages.list_room_memory_facts", return_value=[]),
            patch("blueprints.chat.messages.rebuild_room_summary"),
            patch(
                "blueprints.chat.messages.consume_llm_daily_quota",
                return_value=(True, 1, 300),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=delayed_stream,
            ),
        ):
            response = asyncio.run(chat(request))
            self.assertIsInstance(response, StreamingResponse)

            generation_key = build_generation_key(chat_room_id="room-1", user_id=42)
            self.assertTrue(has_active_generation(generation_key))

            status_request = build_request(
                method="GET",
                path="/api/chat_generation_status",
                session=session,
                query_string=b"room_id=room-1",
            )
            status_response = asyncio.run(chat_generation_status(status_request))
            status_payload = json.loads(status_response.body.decode("utf-8"))
            self.assertTrue(status_payload["is_generating"])

            release_generation.set()
            self.assertTrue(generation_finished.wait(timeout=1.0))
            self.assertFalse(has_active_generation(generation_key))

            history_request = build_request(
                method="GET",
                path="/api/get_chat_history",
                session=session,
                query_string=b"room_id=room-1",
            )
            history_response = asyncio.run(get_chat_history(history_request))
            history_payload = json.loads(history_response.body.decode("utf-8"))

        self.assertEqual(
            [message["sender"] for message in history_payload["messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(history_payload["messages"][-1]["message"], "完了")

    def test_get_chat_history_forwards_limit_and_before_id(self):
        session = {"user_id": 24}
        history_request = build_request(
            method="GET",
            path="/api/get_chat_history",
            session=session,
            query_string=b"room_id=room-7&limit=25&before_id=88",
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                with patch(
                    "blueprints.chat.messages._fetch_chat_history",
                    return_value={
                        "messages": [],
                        "pagination": {
                            "limit": 25,
                            "has_more": True,
                            "next_before_id": 63,
                        },
                    },
                ) as fetch_history:
                    history_response = asyncio.run(get_chat_history(history_request))

        payload = json.loads(history_response.body.decode("utf-8"))
        self.assertEqual(payload["pagination"]["limit"], 25)
        self.assertTrue(payload["pagination"]["has_more"])
        fetch_history.assert_called_once_with("room-7", 25, 88)

    def test_get_chat_history_falls_back_to_shared_default_limit(self):
        session = {"user_id": 24}
        history_request = build_request(
            method="GET",
            path="/api/get_chat_history",
            session=session,
            query_string=b"room_id=room-7",
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                with patch(
                    "blueprints.chat.messages._fetch_chat_history",
                    return_value={
                        "messages": [],
                        "pagination": {
                            "limit": CHAT_HISTORY_PAGE_SIZE_DEFAULT,
                            "has_more": False,
                            "next_before_id": None,
                        },
                    },
                ) as fetch_history:
                    history_response = asyncio.run(get_chat_history(history_request))

        payload = json.loads(history_response.body.decode("utf-8"))
        self.assertEqual(payload["pagination"]["limit"], CHAT_HISTORY_PAGE_SIZE_DEFAULT)
        fetch_history.assert_called_once_with("room-7", CHAT_HISTORY_PAGE_SIZE_DEFAULT, None)

    def test_get_chat_history_rejects_guest_room_not_registered_in_session(self):
        history_request = build_request(
            method="GET",
            path="/api/get_chat_history",
            session={"guest_room_ids": ["room-owned"]},
            query_string=b"room_id=room-target",
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.get_session_id", return_value="sid-1"):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists") as mock_room_exists:
                    history_response = asyncio.run(get_chat_history(history_request))

        self.assertEqual(history_response.status_code, 404)
        mock_room_exists.assert_not_called()

    def test_chat_generation_stream_rejects_guest_room_not_registered_in_session(self):
        stream_request = build_request(
            method="GET",
            path="/api/chat_generation_stream",
            session={"guest_room_ids": ["room-owned"]},
            query_string=b"room_id=room-target",
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.get_session_id", return_value="sid-1"):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists") as mock_room_exists:
                    stream_response = asyncio.run(chat_generation_stream(stream_request))

        self.assertEqual(stream_response.status_code, 404)
        mock_room_exists.assert_not_called()


    def test_chat_generation_status_includes_has_replayable_job(self):
        session = {"user_id": 99}

        with patch(
            "services.chat_generation.get_llm_response_stream",
            return_value=iter(["完了"]),
        ):
            job_key = build_generation_key(chat_room_id="room-status", user_id=99)
            job = start_generation_job(
                job_key,
                conversation_messages=[{"role": "user", "content": "test"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda _: None,
            )
            # consume all events so the job finishes
            list(_iter_llm_stream_events(job))

        status_request = build_request(
            method="GET",
            path="/api/chat_generation_status",
            session=session,
            query_string=b"room_id=room-status",
        )
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                status_response = asyncio.run(chat_generation_status(status_request))

        payload = json.loads(status_response.body.decode("utf-8"))
        self.assertFalse(payload["is_generating"])
        self.assertTrue(payload["has_replayable_job"])

    def test_chat_generation_stream_replays_completed_job(self):
        session = {"user_id": 77}

        with patch(
            "services.chat_generation.get_llm_response_stream",
            return_value=iter(["再", "生"]),
        ):
            job_key = build_generation_key(chat_room_id="room-replay", user_id=77)
            job = start_generation_job(
                job_key,
                conversation_messages=[{"role": "user", "content": "test"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda _: None,
            )
            # consume all events so the job finishes
            list(_iter_llm_stream_events(job))

        stream_request = build_request(
            method="GET",
            path="/api/chat_generation_stream",
            session=session,
            query_string=b"room_id=room-replay",
        )
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(chat_generation_stream(stream_request))

        self.assertIsInstance(stream_response, StreamingResponse)
        self.assertEqual(stream_response.media_type, "text/event-stream")

        async def _consume():
            chunks = []
            async for chunk in stream_response.body_iterator:
                chunks.append(chunk)
            return b"".join(chunks)

        body = asyncio.run(_consume()).decode("utf-8")
        self.assertIn("event: chunk", body)
        self.assertIn('"text": "再"', body)
        self.assertIn("event: done", body)
        self.assertIn('"response": "再生"', body)

    def test_chat_generation_stream_returns_404_when_no_job(self):
        session = {"user_id": 55}

        stream_request = build_request(
            method="GET",
            path="/api/chat_generation_stream",
            session=session,
            query_string=b"room_id=room-nonexistent",
        )
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(chat_generation_stream(stream_request))

        self.assertEqual(stream_response.status_code, 404)

    def test_chat_generation_stream_skips_already_received_events_via_last_event_id(self):
        session = {"user_id": 81}

        with patch(
            "services.chat_generation.get_llm_response_stream",
            return_value=iter(["A", "B"]),
        ):
            job_key = build_generation_key(chat_room_id="room-last-id", user_id=81)
            job = start_generation_job(
                job_key,
                conversation_messages=[{"role": "user", "content": "test"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda _: None,
            )
            list(_iter_llm_stream_events(job))

        stream_request = build_request(
            method="GET",
            path="/api/chat_generation_stream",
            session=session,
            query_string=b"room_id=room-last-id",
            headers=[(b"last-event-id", b"1")],
        )
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(chat_generation_stream(stream_request))

        async def _consume():
            chunks = []
            async for chunk in stream_response.body_iterator:
                chunks.append(chunk)
            return b"".join(chunks)

        body = asyncio.run(_consume()).decode("utf-8")
        self.assertEqual(body.count("event: chunk"), 1)
        self.assertIn('"text": "B"', body)
        self.assertIn("event: done", body)

    def test_chat_generation_stream_replays_distributed_events_without_local_job(self):
        session = {"user_id": 88}
        fake_redis = _FakeRedis()
        service = ChatGenerationService(redis_client_getter=lambda: fake_redis)
        job_key = build_generation_key(chat_room_id="room-distributed", user_id=88)

        fake_redis.rpush(
            service._event_stream_key(job_key),
            json.dumps({"id": 1, "event": "chunk", "payload": {"text": "分散"}}),
        )
        fake_redis.rpush(
            service._event_stream_key(job_key),
            json.dumps({"id": 2, "event": "done", "payload": {"response": "分散完了"}}),
        )

        stream_request = build_request(
            method="GET",
            path="/api/chat_generation_stream",
            session=session,
            query_string=b"room_id=room-distributed",
        )
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(
                    chat_generation_stream(
                        stream_request,
                        chat_generation_service=service,
                    )
                )

        self.assertIsInstance(stream_response, StreamingResponse)

        async def _consume():
            chunks = []
            async for chunk in stream_response.body_iterator:
                chunks.append(chunk)
            return b"".join(chunks)

        body = asyncio.run(_consume()).decode("utf-8")
        self.assertIn("event: chunk", body)
        self.assertIn('"text": "分散"', body)
        self.assertIn("event: done", body)
        self.assertIn('"response": "分散完了"', body)

    def test_chat_generation_stream_times_out_stalled_distributed_job(self):
        session = {"user_id": 90}
        fake_redis = _FakeRedisWithPubSub()
        service = ChatGenerationService(
            redis_client_getter=lambda: fake_redis,
            distributed_stream_idle_timeout_seconds=0.0,
        )
        job_key = build_generation_key(chat_room_id="room-stalled", user_id=90)
        fake_redis.set(service._active_lock_key(job_key), "lock-token")

        stream_request = build_request(
            method="GET",
            path="/api/chat_generation_stream",
            session=session,
            query_string=b"room_id=room-stalled",
        )
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(
                    chat_generation_stream(
                        stream_request,
                        chat_generation_service=service,
                    )
                )

        self.assertIsInstance(stream_response, StreamingResponse)

        async def _consume():
            chunks = []
            async for chunk in stream_response.body_iterator:
                chunks.append(chunk)
            return b"".join(chunks)

        body = asyncio.run(_consume()).decode("utf-8")
        self.assertIn("event: error", body)
        self.assertIn('"retryable": true', body)
        self.assertIn("応答ストリームが一定時間更新されなかったため接続を終了しました。", body)
        self.assertTrue(fake_redis.pubsub_instance.closed)


if __name__ == "__main__":
    unittest.main()
