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
    chat_edit_and_regenerate,
    chat_regenerate,
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
from services.llm import LlmConfigurationError, LlmTimeoutError
from services.web_search import WebSearchAugmentation, WebSearchResult, WebSearchSource
from tests.helpers.request_helpers import build_request


# 日本語: FakeRedisPipeline に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeRedisPipeline.
class _FakeRedisPipeline:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, redis_client):
        self._redis = redis_client
        self._commands = []

    # 日本語: rpush に関する処理の入口です。
    # English: Entry point for logic related to rpush.
    def rpush(self, key, value):
        self._commands.append(("rpush", key, value))
        return self

    # 日本語: expire に関する処理の入口です。
    # English: Entry point for logic related to expire.
    def expire(self, key, ttl):
        self._commands.append(("expire", key, ttl))
        return self

    # 日本語: publish に関する処理の入口です。
    # English: Entry point for logic related to publish.
    def publish(self, channel, message):
        self._commands.append(("publish", channel, message))
        return self

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self):
        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
        for command, key, value in self._commands:
            getattr(self._redis, command)(key, value)
        self._commands.clear()
        return True


# 日本語: FakeRedis に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeRedis.
class _FakeRedis:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        self._values = {}
        self._lists = {}

    # 日本語: set の設定処理を担当します。
    # English: Handle setting for set.
    def set(self, key, value, nx=False, ex=None):
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if nx and key in self._values:
            return False
        self._values[key] = value
        return True

    # 日本語: exists に関する処理の入口です。
    # English: Entry point for logic related to exists.
    def exists(self, key):
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if key in self._values:
            return 1
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if key in self._lists and len(self._lists[key]) > 0:
            return 1
        return 0

    # 日本語: lrange に関する処理の入口です。
    # English: Entry point for logic related to lrange.
    def lrange(self, key, start, end):
        values = list(self._lists.get(key, []))
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not values:
            return []
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if end < 0:
            end = len(values) - 1
        return values[start : end + 1]

    # 日本語: rpush に関する処理の入口です。
    # English: Entry point for logic related to rpush.
    def rpush(self, key, value):
        self._lists.setdefault(key, []).append(value)
        return len(self._lists[key])

    # 日本語: expire に関する処理の入口です。
    # English: Entry point for logic related to expire.
    def expire(self, key, ttl):
        return True

    # 日本語: publish に関する処理の入口です。
    # English: Entry point for logic related to publish.
    def publish(self, channel, message):
        return 1

    # 日本語: pipeline に関する処理の入口です。
    # English: Entry point for logic related to pipeline.
    def pipeline(self):
        return _FakeRedisPipeline(self)

    # 日本語: eval に関する処理の入口です。
    # English: Entry point for logic related to eval.
    def eval(self, *_args, **_kwargs):
        return 1


# 日本語: SilentPubSub に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to SilentPubSub.
class _SilentPubSub:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        self.channels = []
        self.closed = False

    # 日本語: subscribe に関する処理の入口です。
    # English: Entry point for logic related to subscribe.
    def subscribe(self, channel):
        self.channels.append(channel)

    # 日本語: get message の取得処理を担当します。
    # English: Handle fetching for get message.
    def get_message(self, timeout=0.0):
        return None

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: FakeRedisWithPubSub に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeRedisWithPubSub.
class _FakeRedisWithPubSub(_FakeRedis):
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        super().__init__()
        self.pubsub_instance = _SilentPubSub()

    # 日本語: pubsub に関する処理の入口です。
    # English: Entry point for logic related to pubsub.
    def pubsub(self, ignore_subscribe_messages=True):
        return self.pubsub_instance


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/chat",
        json_body=json_body,
        session=session,
    )


# 日本語: ChatStreamingTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatStreamingTestCase.
class ChatStreamingTestCase(unittest.TestCase):
    # 日本語: setUp に関する処理の入口です。
    # English: Entry point for logic related to setUp.
    def setUp(self):
        clear_generation_job_state(cancel_running=True)

    # 日本語: tearDown に関する処理の入口です。
    # English: Entry point for logic related to tearDown.
    def tearDown(self):
        clear_generation_job_state(cancel_running=True)

    # 日本語: test truncate conversation for llm keeps system and recent history のテスト検証を担当します。
    # English: Handle verifying test behavior for test truncate conversation for llm keeps system and recent history.
    def test_truncate_conversation_for_llm_keeps_system_and_recent_history(self):
        messages = [{"role": "system", "content": "system"}]
        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
        for index in range(60):
            role = "user" if index % 2 == 0 else "assistant"
            messages.append({"role": role, "content": f"msg-{index}"})

        truncated = _truncate_conversation_for_llm(messages)

        self.assertEqual(truncated[0]["role"], "system")
        self.assertLessEqual(len(truncated), 41)
        self.assertEqual(truncated[-1]["content"], "msg-59")

    # 日本語: test paginate ephemeral chat history reports has more and cursor のテスト検証を担当します。
    # English: Handle verifying test behavior for test paginate ephemeral chat history reports has more and cursor.
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

    # 日本語: test paginate ephemeral chat history respects before id cursor のテスト検証を担当します。
    # English: Handle verifying test behavior for test paginate ephemeral chat history respects before id cursor.
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

    # 日本語: test chat returns streaming response for gemini のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat returns streaming response for gemini.
    def test_chat_returns_streaming_response_for_gemini(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "gemini-2.5-flash"},
            session={},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test chat returns streaming response for groq のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat returns streaming response for groq.
    def test_chat_returns_streaming_response_for_groq(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "openai/gpt-oss-120b"},
            session={},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test chat rejects invalid model before persisting authenticated message のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat rejects invalid model before persisting authenticated message.
    def test_chat_rejects_invalid_model_before_persisting_authenticated_message(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "room-auth", "model": "invalid-model"},
            session={"user_id": 42},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test streaming generation error discards guest room without assistant reply のテスト検証を担当します。
    # English: Handle verifying test behavior for test streaming generation error discards guest room without assistant reply.
    def test_streaming_generation_error_discards_guest_room_without_assistant_reply(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "room-guest", "model": "gemini-2.5-flash"},
            session={},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

                                            # 日本語: consume に関する処理の入口です。
                                            # English: Entry point for logic related to consume.
                                            async def _consume():
                                                chunks = []
                                                # 日本語: 非同期の対象データを順番に処理します。
                                                # English: Process each asynchronous target item in order.
                                                async for chunk in response.body_iterator:
                                                    chunks.append(chunk)
                                                return b"".join(chunks)

                                            body = asyncio.run(_consume()).decode("utf-8")

        self.assertIsInstance(response, StreamingResponse)
        self.assertIn("event: error", body)
        self.assertIn("OPENAI_API_KEY が未設定です。", body)
        mock_delete_room.assert_called_once_with("sid-1", "room-guest")

    # 日本語: test background generation job persists final reply for guest のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job persists final reply for guest.
    def test_background_generation_job_persists_final_reply_for_guest(self):
        persisted_messages = []

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test background generation job includes persist metadata in done event のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job includes persist metadata in done event.
    def test_background_generation_job_includes_persist_metadata_in_done_event(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "services.chat_generation.get_llm_response_stream",
            return_value=iter(["hello"]),
        ):
            job = start_generation_job(
                "user:1:room-title",
                conversation_messages=[{"role": "user", "content": "hello"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda _response: {"room_title": "Short title"},
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: done", body)
        self.assertIn('"room_title": "Short title"', body)

    # 日本語: test background generation job streams valid generative ui parts before done のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job streams valid generative ui parts before done.
    def test_background_generation_job_streams_valid_generative_ui_parts_before_done(self):
        artifact_block = (
            "説明します。\n"
            "```chatcore-artifact\n"
            "{"
            '"version":1,'
            '"title":"構成図",'
            '"html":"<div id=\\"app\\"></div>",'
            '"css":"#app{padding:12px;}",'
            '"js":"document.getElementById(\\"app\\").textContent = \\"ready\\";"'
            "}\n"
            "```"
        )

        persisted_messages = []

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "services.chat_generation.get_llm_response_stream",
            return_value=iter([artifact_block[:40], artifact_block[40:]]),
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "図で説明して"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response, message_parts=None: persisted_messages.append(
                    (response, message_parts)
                ),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: response_parts_updated", body)
        self.assertIn('"type": "sandbox_artifact"', body)
        self.assertIn('"response": "説明します。"', body)
        self.assertIn("event: done", body)
        self.assertEqual(persisted_messages[0][0], "説明します。")
        self.assertEqual(persisted_messages[0][1][1]["type"], "sandbox_artifact")

    # 日本語: test background generation job appends web search sources to reply のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job appends web search sources to reply.
    def test_background_generation_job_appends_web_search_sources_to_reply(self):
        persisted_messages = []
        search_result = WebSearchResult(
            query="Python news",
            searched_at="2026-04-30T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/python",
                    title="Python News",
                    hostname="example.com",
                    age="2026-04-30",
                    snippets=(),
                ),
            ),
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "Pythonの最新ニュース"}],
                    result=search_result,
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                return_value=iter(["回答本文"]),
            ),
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "Pythonの最新ニュース"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("回答本文", body)
        self.assertIn('\\"web-search-sources__summary\\"', body)
        self.assertIn('\\"web-search-sources__label\\">回答までのステップ', body)
        self.assertIn('\\"web-search-sources__count\\">4ステップ / 1件', body)
        self.assertIn("https://example.com/python", persisted_messages[0])
        self.assertTrue(persisted_messages[0].startswith('<details class="web-search-sources web-search-sources--trace">'))
        self.assertIn('<summary class="web-search-sources__summary">', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__label">回答までのステップ</span>', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__count">4ステップ / 1件</span>', persisted_messages[0])
        self.assertIn("回答本文", persisted_messages[0])

    # 日本語: test background generation job can search again after reviewing results のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job can search again after reviewing results.
    def test_background_generation_job_can_search_again_after_reviewing_results(self):
        persisted_messages = []
        stream_call_count = 0
        search_results = {
            "Python latest news": WebSearchResult(
                query="Python latest news",
                searched_at="2026-04-30T00:00:00+00:00",
                sources=(
                    WebSearchSource(
                        url="https://example.com/python",
                        title="Python News",
                        hostname="example.com",
                        age="2026-04-30",
                        snippets=("Python update",),
                    ),
                ),
            ),
            "Python release details": WebSearchResult(
                query="Python release details",
                searched_at="2026-04-30T00:01:00+00:00",
                sources=(
                    WebSearchSource(
                        url="https://example.com/release",
                        title="Python Release",
                        hostname="example.com",
                        age="2026-04-30",
                        snippets=("Release detail",),
                    ),
                ),
            ),
        }

        # 日本語: stream side effect のストリーミング処理を担当します。
        # English: Handle streaming for stream side effect.
        def stream_side_effect(_messages, _model, *, tools=None):
            nonlocal stream_call_count
            stream_call_count += 1
            # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
            # English: Switch the flow according to the current condition.
            if stream_call_count == 1:
                yield json.dumps(
                    [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": "Python latest news"}),
                            },
                        }
                    ]
                )
                return
            # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
            # English: Switch the flow according to the current condition.
            if stream_call_count == 2:
                yield json.dumps(
                    [
                        {
                            "id": "call-2",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": "Python release details"}),
                            },
                        }
                    ]
                )
                return
            self.assertIsNotNone(tools)
            yield "検索結果を踏まえた回答"

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "Pythonの最新情報を詳しく"}],
                ),
            ),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream_side_effect),
            patch(
                "services.chat_generation.search_brave_llm_context",
                side_effect=lambda query, freshness="": search_results[query],
            ) as mock_search,
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "Pythonの最新情報を詳しく"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(stream_call_count, 3)
        self.assertEqual(
            [call.args[0] for call in mock_search.call_args_list],
            ["Python latest news", "Python release details"],
        )
        self.assertIn("検索結果を踏まえた回答", body)
        self.assertIn("https://example.com/python", persisted_messages[0])
        self.assertIn("https://example.com/release", persisted_messages[0])
        self.assertIn('<span class="web-search-sources__title">Web検索: Python latest news</span>', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__title">追加検索: Python release details</span>', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__count">5ステップ / 2件</span>', persisted_messages[0])

    # 日本語: test background generation job reuses duplicate search results のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job reuses duplicate search results.
    def test_background_generation_job_reuses_duplicate_search_results(self):
        persisted_messages = []
        stream_call_count = 0
        search_result = WebSearchResult(
            query="OpenAI news",
            searched_at="2026-04-30T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/openai",
                    title="OpenAI News",
                    hostname="example.com",
                    age="2026-04-30",
                    snippets=("OpenAI update",),
                ),
            ),
        )

        # 日本語: stream side effect のストリーミング処理を担当します。
        # English: Handle streaming for stream side effect.
        def stream_side_effect(_messages, _model, *, tools=None):
            nonlocal stream_call_count
            stream_call_count += 1
            # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
            # English: Switch the flow according to the current condition.
            if stream_call_count <= 2:
                yield json.dumps(
                    [
                        {
                            "id": f"call-{stream_call_count}",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": "OpenAI news"}),
                            },
                        }
                    ]
                )
                return
            yield "回答"

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "OpenAIニュース"}],
                ),
            ),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream_side_effect),
            patch(
                "services.chat_generation.search_brave_llm_context",
                return_value=search_result,
            ) as mock_search,
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "OpenAIニュース"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(stream_call_count, 3)
        mock_search.assert_called_once_with("OpenAI news", freshness="")
        self.assertIn('"cached": true', body)
        self.assertIn('<span class="web-search-sources__title">検索結果を再利用: OpenAI news</span>', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__count">5ステップ / 1件</span>', persisted_messages[0])

    # 日本語: test background generation job stops tool loop at max steps のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job stops tool loop at max steps.
    def test_background_generation_job_stops_tool_loop_at_max_steps(self):
        persisted_messages = []
        stream_tools: list[bool] = []
        search_index = 0

        # 日本語: stream side effect のストリーミング処理を担当します。
        # English: Handle streaming for stream side effect.
        def stream_side_effect(_messages, _model, *, tools=None):
            stream_tools.append(bool(tools))
            # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
            # English: Switch the flow according to the current condition.
            if tools:
                query = f"loop search {len(stream_tools)}"
                yield json.dumps(
                    [
                        {
                            "id": f"call-{len(stream_tools)}",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": query}),
                            },
                        }
                    ]
                )
                return
            yield "上限内で回答"

        # 日本語: search side effect に関する処理の入口です。
        # English: Entry point for logic related to search side effect.
        def search_side_effect(query, freshness=""):
            nonlocal search_index
            search_index += 1
            return WebSearchResult(
                query=query,
                searched_at=f"2026-04-30T00:0{search_index}:00+00:00",
                sources=(
                    WebSearchSource(
                        url=f"https://example.com/{search_index}",
                        title=f"Source {search_index}",
                        hostname="example.com",
                        age="2026-04-30",
                        snippets=(query,),
                    ),
                ),
            )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch.dict("services.chat_generation.os.environ", {"CHAT_AGENT_MAX_STEPS": "10"}, clear=False),
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "調べ続けて"}],
                ),
            ),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream_side_effect),
            patch("services.chat_generation.search_brave_llm_context", side_effect=search_side_effect) as mock_search,
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "調べ続けて"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(mock_search.call_count, 4)
        self.assertEqual(stream_tools, [True, True, True, True, False])
        self.assertIn("上限内で回答", body)
        self.assertIn('<span class="web-search-sources__count">9ステップ / 4件</span>', persisted_messages[0])

    # 日本語: test background generation job reports response generation status のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job reports response generation status.
    def test_background_generation_job_reports_response_generation_status(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "こんにちは"}],
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                return_value=iter(["回答"]),
            ),
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "こんにちは"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda _: None,
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: response_generation_started", body)
        self.assertIn("event: chunk", body)

    # 日本語: test background generation job keeps web search failure status until chunk のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job keeps web search failure status until chunk.
    def test_background_generation_job_keeps_web_search_failure_status_until_chunk(self):
        # 日本語: failed augment に関する処理の入口です。
        # English: Entry point for logic related to failed augment.
        def failed_augment(messages, _model, *, publish_event=None):
            # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
            # English: Switch the flow according to the current condition.
            if publish_event is not None:
                publish_event("web_search_planning_started", {})
                publish_event(
                    "web_search_failed",
                    {"query": "news", "message": "Web検索に失敗しました。"},
                )
            return WebSearchAugmentation(messages=messages, status="failed")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                side_effect=failed_augment,
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                return_value=iter(["回答"]),
            ),
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "今日のニュース"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda _: None,
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: web_search_failed", body)
        self.assertNotIn("event: response_generation_started", body)
        self.assertIn("event: chunk", body)

    # 日本語: test background generation job surfaces configuration error message のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job surfaces configuration error message.
    def test_background_generation_job_surfaces_configuration_error_message(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=LlmConfigurationError("OPENAI_API_KEY が未設定です。"),
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "こんにちは"}],
                model="gpt-5-mini",
                persist_response=lambda _: None,
            )
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: error", body)
        self.assertIn("OPENAI_API_KEY が未設定です。", body)

    # 日本語: test background generation job retries transient error before output のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job retries transient error before output.
    def test_background_generation_job_retries_transient_error_before_output(self):
        attempts = {"count": 0}

        # 日本語: flaky stream に関する処理の入口です。
        # English: Entry point for logic related to flaky stream.
        def flaky_stream(*_args, **_kwargs):
            attempts["count"] += 1
            # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
            # English: Switch the flow according to the current condition.
            if attempts["count"] == 1:
                raise LlmTimeoutError("provider timed out")
            yield from ["こん", "にちは"]

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.chat_generation._llm_stream_retry_delay", return_value=0.0):
            with patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=flaky_stream,
            ):
                job = start_generation_job(
                    "guest:sid-1:default",
                    conversation_messages=[{"role": "user", "content": "こんにちは"}],
                    model="openai/gpt-oss-120b",
                    persist_response=lambda _: None,
                )
                body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(attempts["count"], 2)
        self.assertNotIn("event: error", body)
        self.assertIn("event: done", body)
        self.assertIn('"response": "こんにちは"', body)

    # 日本語: test background generation job does not retry after chunk emitted のテスト検証を担当します。
    # English: Handle verifying test behavior for test background generation job does not retry after chunk emitted.
    def test_background_generation_job_does_not_retry_after_chunk_emitted(self):
        attempts = {"count": 0}

        # 日本語: flaky stream に関する処理の入口です。
        # English: Entry point for logic related to flaky stream.
        def flaky_stream(*_args, **_kwargs):
            attempts["count"] += 1
            yield "partial"
            raise LlmTimeoutError("provider timed out mid-stream")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.chat_generation._llm_stream_retry_delay", return_value=0.0):
            with patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=flaky_stream,
            ):
                job = start_generation_job(
                    "guest:sid-1:default",
                    conversation_messages=[{"role": "user", "content": "hi"}],
                    model="openai/gpt-oss-120b",
                    persist_response=lambda _: None,
                )
                body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        # Already-emitted output must not trigger a retry that would duplicate it.
        self.assertEqual(attempts["count"], 1)
        self.assertIn("event: error", body)

    # 日本語: test has active generation is false after job completion のテスト検証を担当します。
    # English: Handle verifying test behavior for test has active generation is false after job completion.
    def test_has_active_generation_is_false_after_job_completion(self):
        release_generation = threading.Event()

        # 日本語: delayed stream に関する処理の入口です。
        # English: Entry point for logic related to delayed stream.
        def delayed_stream(*_args, **_kwargs):
            release_generation.wait(timeout=1.0)
            yield "ok"

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test start generation job rejects duplicate active job のテスト検証を担当します。
    # English: Handle verifying test behavior for test start generation job rejects duplicate active job.
    def test_start_generation_job_rejects_duplicate_active_job(self):
        release_generation = threading.Event()

        # 日本語: delayed stream に関する処理の入口です。
        # English: Entry point for logic related to delayed stream.
        def delayed_stream(*_args, **_kwargs):
            release_generation.wait(timeout=1.0)
            yield "done"

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test generation continues after disconnect and reopen returns completed reply のテスト検証を担当します。
    # English: Handle verifying test behavior for test generation continues after disconnect and reopen returns completed reply.
    def test_generation_continues_after_disconnect_and_reopen_returns_completed_reply(self):
        stored_messages = []
        release_generation = threading.Event()
        generation_finished = threading.Event()
        session = {"user_id": 42}

        # 日本語: save message の保存処理を担当します。
        # English: Handle saving for save message.
        def save_message(room_id, message, sender, attached_file_names=None, parent_id=None):
            stored_messages.append((room_id, message, sender))
            # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
            # English: Switch the flow according to the current condition.
            if sender == "assistant":
                generation_finished.set()
            return len(stored_messages)

        # 日本語: active leaf id に関する処理の入口です。
        # English: Entry point for logic related to active leaf id.
        def active_leaf_id(room_id):
            room_messages = [m for m in stored_messages if m[0] == room_id]
            return len(room_messages) or None

        # 日本語: get messages の取得処理を担当します。
        # English: Handle fetching for get messages.
        def get_messages(room_id):
            return [
                {
                    "role": "user" if sender == "user" else "assistant",
                    "content": message,
                }
                for stored_room_id, message, sender in stored_messages
                if stored_room_id == room_id
            ]

        # 日本語: fetch history の取得処理を担当します。
        # English: Handle fetching for fetch history.
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

        # 日本語: delayed stream に関する処理の入口です。
        # English: Entry point for logic related to delayed stream.
        def delayed_stream(*_args, **_kwargs):
            yield "完"
            release_generation.wait(timeout=1.0)
            yield "了"

        request = make_request(
            {"message": "こんにちは", "chat_room_id": "room-1", "model": "openai/gpt-oss-120b"},
            session=session,
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("blueprints.chat.messages.cleanup_ephemeral_chats"),
            patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)),
            patch("blueprints.chat.messages.save_message_to_db", side_effect=save_message),
            patch("blueprints.chat.messages.get_active_leaf_id", side_effect=active_leaf_id),
            patch("blueprints.chat.messages.get_chat_room_messages", side_effect=get_messages),
            patch("blueprints.chat.messages._fetch_chat_history", side_effect=fetch_history),
            patch("blueprints.chat.messages.get_user_by_id", return_value={}),
            patch("blueprints.chat.messages.get_room_summary", return_value={}),
            patch("blueprints.chat.messages.list_room_memory_facts", return_value=[]),
            patch("blueprints.chat.messages.rebuild_room_summary"),
            patch("services.chat_use_case.maybe_auto_title_chat_room", return_value=None),
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

    # 日本語: test regenerate reinjects saved attachment contents for llm のテスト検証を担当します。
    # English: Handle verifying test behavior for test regenerate reinjects saved attachment contents for llm.
    def test_regenerate_reinjects_saved_attachment_contents_for_llm(self):
        captured_messages = {}
        request = build_request(
            method="POST",
            path="/api/chat_regenerate",
            json_body={"chat_room_id": "room-1", "model": "gemini-2.5-flash"},
            session={"user_id": 42},
        )

        # 日本語: get llm response の取得処理を担当します。
        # English: Handle fetching for get llm response.
        def get_llm_response(messages, model):
            captured_messages["messages"] = messages
            return "new answer"

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("blueprints.chat.messages.cleanup_ephemeral_chats"),
            patch("blueprints.chat.messages.validate_model_name"),
            patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)),
            patch(
                "blueprints.chat.messages.get_active_path",
                return_value=[
                    {
                        "id": 10,
                        "message": "要約して",
                        "sender": "user",
                        "attached_file_names": ["sample.pdf"],
                        "attached_file_contents": [
                            {"name": "sample.pdf", "content": "[page 1]\nPDF BODY"}
                        ],
                    },
                    {"id": 11, "message": "old answer", "sender": "assistant"},
                ],
            ),
            patch("blueprints.chat.messages.get_user_by_id", return_value={}),
            patch("blueprints.chat.messages.get_room_summary", return_value={}),
            patch("blueprints.chat.messages.list_room_memory_facts", return_value=[]),
            patch("blueprints.chat.messages.consume_llm_daily_quota", return_value=(True, 1, 300)),
            patch("blueprints.chat.messages.is_streaming_model", return_value=False),
            patch("blueprints.chat.messages.get_llm_response", side_effect=get_llm_response),
            patch("blueprints.chat.messages.save_message_to_db", return_value=12),
        ):
            response = asyncio.run(chat_regenerate(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "new answer")
        contents = [message["content"] for message in captured_messages["messages"]]
        self.assertTrue(any("PDF BODY" in content for content in contents))
        self.assertFalse(any("old answer" in content for content in contents))

    # 日本語: test edit and regenerate carries original attachment contents のテスト検証を担当します。
    # English: Handle verifying test behavior for test edit and regenerate carries original attachment contents.
    def test_edit_and_regenerate_carries_original_attachment_contents(self):
        captured_messages = {}
        saved_messages = []
        request = build_request(
            method="POST",
            path="/api/chat_edit_and_regenerate",
            json_body={
                "chat_room_id": "room-1",
                "new_message": "この資料を短く要約して",
                "trailing_user_count": 0,
                "model": "gemini-2.5-flash",
            },
            session={"user_id": 42},
        )

        # 日本語: save message の保存処理を担当します。
        # English: Handle saving for save message.
        def save_message(*args, **kwargs):
            saved_messages.append((args, kwargs))
            return 20 + len(saved_messages)

        # 日本語: get llm response の取得処理を担当します。
        # English: Handle fetching for get llm response.
        def get_llm_response(messages, model):
            captured_messages["messages"] = messages
            return "edited answer"

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("blueprints.chat.messages.cleanup_ephemeral_chats"),
            patch("blueprints.chat.messages.validate_model_name"),
            patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)),
            patch(
                "blueprints.chat.messages.get_active_path",
                return_value=[
                    {
                        "id": 10,
                        "message": "要約して",
                        "sender": "user",
                        "attached_file_names": ["sample.pdf"],
                        "attached_file_contents": [
                            {"name": "sample.pdf", "content": "[page 1]\nPDF BODY"}
                        ],
                    },
                    {"id": 11, "message": "old answer", "sender": "assistant"},
                ],
            ),
            patch("blueprints.chat.messages.get_user_by_id", return_value={}),
            patch("blueprints.chat.messages.get_room_summary", return_value={}),
            patch("blueprints.chat.messages.list_room_memory_facts", return_value=[]),
            patch("blueprints.chat.messages.consume_llm_daily_quota", return_value=(True, 1, 300)),
            patch("blueprints.chat.messages.is_streaming_model", return_value=False),
            patch("blueprints.chat.messages.get_llm_response", side_effect=get_llm_response),
            patch("blueprints.chat.messages.save_message_to_db", side_effect=save_message),
        ):
            response = asyncio.run(chat_edit_and_regenerate(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "edited answer")
        contents = [message["content"] for message in captured_messages["messages"]]
        self.assertTrue(any("PDF BODY" in content for content in contents))
        user_save_args, user_save_kwargs = saved_messages[0]
        self.assertEqual(user_save_args[3], ["sample.pdf"])
        self.assertIn("attached_file_contents", user_save_kwargs)

    # 日本語: test get chat history forwards limit and before id のテスト検証を担当します。
    # English: Handle verifying test behavior for test get chat history forwards limit and before id.
    def test_get_chat_history_forwards_limit_and_before_id(self):
        session = {"user_id": 24}
        history_request = build_request(
            method="GET",
            path="/api/get_chat_history",
            session=session,
            query_string=b"room_id=room-7&limit=25&before_id=88",
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test get chat history falls back to shared default limit のテスト検証を担当します。
    # English: Handle verifying test behavior for test get chat history falls back to shared default limit.
    def test_get_chat_history_falls_back_to_shared_default_limit(self):
        session = {"user_id": 24}
        history_request = build_request(
            method="GET",
            path="/api/get_chat_history",
            session=session,
            query_string=b"room_id=room-7",
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test get chat history rejects guest room not registered in session のテスト検証を担当します。
    # English: Handle verifying test behavior for test get chat history rejects guest room not registered in session.
    def test_get_chat_history_rejects_guest_room_not_registered_in_session(self):
        history_request = build_request(
            method="GET",
            path="/api/get_chat_history",
            session={"guest_room_ids": ["room-owned"]},
            query_string=b"room_id=room-target",
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.get_session_id", return_value="sid-1"):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists") as mock_room_exists:
                    history_response = asyncio.run(get_chat_history(history_request))

        self.assertEqual(history_response.status_code, 404)
        mock_room_exists.assert_not_called()

    # 日本語: test chat generation stream rejects guest room not registered in session のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat generation stream rejects guest room not registered in session.
    def test_chat_generation_stream_rejects_guest_room_not_registered_in_session(self):
        stream_request = build_request(
            method="GET",
            path="/api/chat_generation_stream",
            session={"guest_room_ids": ["room-owned"]},
            query_string=b"room_id=room-target",
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.get_session_id", return_value="sid-1"):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists") as mock_room_exists:
                    stream_response = asyncio.run(chat_generation_stream(stream_request))

        self.assertEqual(stream_response.status_code, 404)
        mock_room_exists.assert_not_called()


    # 日本語: test chat generation status includes has replayable job のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat generation status includes has replayable job.
    def test_chat_generation_status_includes_has_replayable_job(self):
        session = {"user_id": 99}

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                status_response = asyncio.run(chat_generation_status(status_request))

        payload = json.loads(status_response.body.decode("utf-8"))
        self.assertFalse(payload["is_generating"])
        self.assertTrue(payload["has_replayable_job"])

    # 日本語: test chat generation stream replays completed job のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat generation stream replays completed job.
    def test_chat_generation_stream_replays_completed_job(self):
        session = {"user_id": 77}

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(chat_generation_stream(stream_request))

        self.assertIsInstance(stream_response, StreamingResponse)
        self.assertEqual(stream_response.media_type, "text/event-stream")

        # 日本語: consume に関する処理の入口です。
        # English: Entry point for logic related to consume.
        async def _consume():
            chunks = []
            # 日本語: 非同期の対象データを順番に処理します。
            # English: Process each asynchronous target item in order.
            async for chunk in stream_response.body_iterator:
                chunks.append(chunk)
            return b"".join(chunks)

        body = asyncio.run(_consume()).decode("utf-8")
        self.assertIn("event: chunk", body)
        self.assertIn('"text": "再"', body)
        self.assertIn("event: done", body)
        self.assertIn('"response": "再生"', body)

    # 日本語: test chat generation stream returns 404 when no job のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat generation stream returns 404 when no job.
    def test_chat_generation_stream_returns_404_when_no_job(self):
        session = {"user_id": 55}

        stream_request = build_request(
            method="GET",
            path="/api/chat_generation_stream",
            session=session,
            query_string=b"room_id=room-nonexistent",
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(chat_generation_stream(stream_request))

        self.assertEqual(stream_response.status_code, 404)

    # 日本語: test chat generation stream skips already received events via last event id のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat generation stream skips already received events via last event id.
    def test_chat_generation_stream_skips_already_received_events_via_last_event_id(self):
        session = {"user_id": 81}

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
            headers=[(b"last-event-id", b"3")],
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(chat_generation_stream(stream_request))

        # 日本語: consume に関する処理の入口です。
        # English: Entry point for logic related to consume.
        async def _consume():
            chunks = []
            # 日本語: 非同期の対象データを順番に処理します。
            # English: Process each asynchronous target item in order.
            async for chunk in stream_response.body_iterator:
                chunks.append(chunk)
            return b"".join(chunks)

        body = asyncio.run(_consume()).decode("utf-8")
        self.assertEqual(body.count("event: chunk"), 1)
        self.assertIn('"text": "B"', body)
        self.assertIn("event: done", body)

    # 日本語: test chat generation stream replays distributed events without local job のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat generation stream replays distributed events without local job.
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
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(
                    chat_generation_stream(
                        stream_request,
                        chat_generation_service=service,
                    )
                )

        self.assertIsInstance(stream_response, StreamingResponse)

        # 日本語: consume に関する処理の入口です。
        # English: Entry point for logic related to consume.
        async def _consume():
            chunks = []
            # 日本語: 非同期の対象データを順番に処理します。
            # English: Process each asynchronous target item in order.
            async for chunk in stream_response.body_iterator:
                chunks.append(chunk)
            return b"".join(chunks)

        body = asyncio.run(_consume()).decode("utf-8")
        self.assertIn("event: chunk", body)
        self.assertIn('"text": "分散"', body)
        self.assertIn("event: done", body)
        self.assertIn('"response": "分散完了"', body)

    # 日本語: test chat generation stream times out stalled distributed job のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat generation stream times out stalled distributed job.
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
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(
                    chat_generation_stream(
                        stream_request,
                        chat_generation_service=service,
                    )
                )

        self.assertIsInstance(stream_response, StreamingResponse)

        # 日本語: consume に関する処理の入口です。
        # English: Entry point for logic related to consume.
        async def _consume():
            chunks = []
            # 日本語: 非同期の対象データを順番に処理します。
            # English: Process each asynchronous target item in order.
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
