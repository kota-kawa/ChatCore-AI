import asyncio
import json
import threading
import unittest
from unittest.mock import AsyncMock, patch

from starlette.responses import StreamingResponse

from blueprints.chat.messages import (
    _paginate_ephemeral_chat_history,
    chat,
    chat_edit_and_regenerate,
    chat_regenerate,
    _iter_llm_stream_events,
    _iter_serialized_stream_events,
    chat_generation_status,
    chat_generation_stream,
    get_chat_history,
)
from services.chat_contract import CHAT_HISTORY_PAGE_SIZE_DEFAULT
from services.error_messages import ERROR_CHAT_EMPTY_RESPONSE
from services.chat_generation import (
    _budgeted_web_search_result_tool_payload,
    _web_search_result_tool_payload,
    ChatGenerationAlreadyRunningError,
    ChatGenerationEvent,
    ChatGenerationService,
    build_generation_key,
    clear_generation_job_state,
    has_active_generation,
    start_generation_job,
)
from services.chat_research_notes import (
    STEP_NOTE_HISTORY_LIMIT,
    STEP_NOTE_MAX_CHARS,
    build_final_answer_messages,
    build_research_loop_messages,
    build_research_wrapup_messages,
    parse_research_summary,
    parse_step_note,
    strip_internal_notes,
)
from services.llm import (
    LlmConfigurationError,
    LlmInputLimitError,
    LlmOutputLimitError,
    LlmTimeoutError,
)
from services.selected_reference_context import (
    PERSONAL_KNOWLEDGE_SOURCE,
    SHARED_PROMPT_SOURCE,
    SelectedReferenceLookupTrace,
)
from services.web_search import (
    build_web_search_system_message,
    create_web_evidence_context_budget,
    WebEvidenceContextBudget,
    WebSearchAugmentation,
    WebSearchResult,
    WebSearchSource,
    WEB_SEARCH_ERROR_REQUEST_FAILED,
    WEB_SEARCH_INITIAL_CONTEXT_MAX_CHARS,
    WEB_SEARCH_MAX_CONTEXT_CHARS,
    WEB_SEARCH_TOOL_CONTEXT_MAX_CHARS,
)
from services.web_search_images import WebSearchImageCandidate
from tests.helpers.request_helpers import build_request


# 日本語: テスト用の疑似Redisパイプラインクラス。コマンドを溜めて一括実行します。
# English: Fake Redis pipeline class for testing, queuing commands for batch execution.
class _FakeRedisPipeline:
    # 日本語: 疑似パイプラインを初期化し、Redisクライアントとコマンドリストを準備します。
    # English: Initialize the fake pipeline and set up the Redis client and command list.
    def __init__(self, redis_client):
        self._redis = redis_client
        self._commands = []

    # 日本語: リストキーの末尾に値を追加し、リストの現在の長さを返します。
    # English: Append a value to the tail of a list key and return its current length.
    def rpush(self, key, value):
        self._commands.append(("rpush", key, value))
        return self

    # 日本語: キーの有効期限を設定します（テスト用のため常に成功を返します）。
    # English: Set the expiration for a key (always returns success for testing).
    def expire(self, key, ttl):
        self._commands.append(("expire", key, ttl))
        return self

    # 日本語: チャンネルにメッセージを送信したフリをします（常に1を返します）。
    # English: Mock publishing a message to a channel (always returns 1).
    def publish(self, channel, message):
        self._commands.append(("publish", channel, message))
        return self

    # 日本語: キューされたすべてのコマンドを疑似Redisクライアントに対して実行します。
    # English: Execute all queued commands against the fake Redis client.
    def execute(self):
        for command, key, value in self._commands:
            getattr(self._redis, command)(key, value)
        self._commands.clear()
        return True


# 日本語: テスト用の疑似Redisクライアント。インメモリ辞書を使用してデータを保持します。
# English: Fake Redis client for testing, storing data in in-memory dictionaries.
class _FakeRedis:
    # 日本語: 疑似Redisのデータストア領域を初期化します。
    # English: Initialize data store areas for fake Redis.
    def __init__(self):
        self._values = {}
        self._lists = {}

    # 日本語: 指定したキーに値を設定します。nx=Trueの場合は存在しないときのみ設定します。
    # English: Set a value for the specified key. If nx=True, set only if it does not exist.
    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._values:
            return False
        self._values[key] = value
        return True

    # 日本語: 指定したキーが疑似Redisに存在するかどうかを確認します。
    # English: Check whether the specified key exists in fake Redis.
    def exists(self, key):
        if key in self._values:
            return 1
        if key in self._lists and len(self._lists[key]) > 0:
            return 1
        return 0

    # 日本語: 指定したリストキーの指定範囲内の要素を取得します。
    # English: Retrieve elements within the specified range from a list key.
    def lrange(self, key, start, end):
        values = list(self._lists.get(key, []))
        if not values:
            return []
        if end < 0:
            end = len(values) - 1
        return values[start : end + 1]

    # 日本語: リストキーの末尾に値を追加し、リストの現在の長さを返します。
    # English: Append a value to the tail of a list key and return its current length.
    def rpush(self, key, value):
        self._lists.setdefault(key, []).append(value)
        return len(self._lists[key])

    # 日本語: キーの有効期限を設定します（テスト用のため常に成功を返します）。
    # English: Set the expiration for a key (always returns success for testing).
    def expire(self, key, ttl):
        return True

    # 日本語: チャンネルにメッセージを送信したフリをします（常に1を返します）。
    # English: Mock publishing a message to a channel (always returns 1).
    def publish(self, channel, message):
        return 1

    # 日本語: 新しい疑似Redisパイプラインインスタンスを返却します。
    # English: Return a new fake Redis pipeline instance.
    def pipeline(self):
        return _FakeRedisPipeline(self)

    # 日本語: RedisのLuaスクリプト評価をシミュレートします（常に1を返します）。
    # English: Simulate Redis Lua script evaluation (always returns 1).
    def eval(self, *_args, **_kwargs):
        return 1


# 日本語: メッセージを出力しないテスト用の疑似PubSubクラス。
# English: Fake PubSub class for testing that does not output messages.
class _SilentPubSub:
    # 日本語: 購読中のチャンネルリストとクローズ状態を初期化します。
    # English: Initialize subscribed channels list and closed state.
    def __init__(self):
        self.channels = []
        self.closed = False

    # 日本語: 指定したチャンネルを購読リストに追加します。
    # English: Add the specified channel to the subscription list.
    def subscribe(self, channel):
        self.channels.append(channel)

    # 日本語: 新しいメッセージを取得します（テスト用のため常にNoneを返します）。
    # English: Get a new message (always returns None for testing).
    def get_message(self, timeout=0.0):
        return None

    # 日本語: 疑似PubSubを閉じます。
    # English: Close the fake PubSub.
    def close(self):
        self.closed = True


# 日本語: PubSub機能を持たせたテスト用の拡張疑似Redisクライアント。
# English: Extended fake Redis client for testing equipped with PubSub functionality.
class _FakeRedisWithPubSub(_FakeRedis):
    # 日本語: 疑似Redisと疑似PubSubインスタンスを初期化します。
    # English: Initialize fake Redis and a fake PubSub instance.
    def __init__(self):
        super().__init__()
        self.pubsub_instance = _SilentPubSub()

    # 日本語: 関連付けられた疑似PubSubインスタンスを返却します。
    # English: Return the associated fake PubSub instance.
    def pubsub(self, ignore_subscribe_messages=True):
        del ignore_subscribe_messages
        return self.pubsub_instance


# 日本語: 新規チャットのテスト用リクエストを構築するヘルパー関数。
# English: Helper function to build a test request for a new chat.
def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/chat",
        json_body=json_body,
        session=session,
    )


def _research_then_answer_stream(*answer_chunks, research_summary=None):
    """Return mock streams for a short research-complete pass followed by final prose."""
    summary_payload = (
        json.dumps(research_summary, ensure_ascii=False)
        if research_summary is not None
        else ""
    )
    return [
        iter([f"<research_complete>{summary_payload}</research_complete>"]),
        iter(answer_chunks),
    ]


# 日本語: チャットのストリーミング応答、検索拡張、履歴制限、再生成などの処理を検証するテストクラス。
# English: Test class to verify chat streaming responses, search augmentation, history limits, and regeneration.
class ChatStreamingTestCase(unittest.TestCase):
    # 日本語: テスト開始前に実行中の一時ジョブ情報をクリアします。
    # English: Clear running temporary job state before starting each test.
    def setUp(self):
        clear_generation_job_state(cancel_running=True)
        self._project_context_patch = patch(
            "blueprints.chat.messages.get_project_context",
            return_value=None,
        )
        self._project_context_patch.start()
        # コンテキスト抽出は専用テストで検証し、チャットルートのテストを実DB設定から分離する。
        # Context extraction is covered by dedicated use-case tests. Keep unrelated
        # chat route tests isolated from the real database-backed opt-in lookup.
        self._context_extraction_patch = patch(
            "blueprints.chat.messages.should_extract_context",
            return_value=False,
        )
        self._context_extraction_patch.start()

    # 日本語: テスト終了後に実行中の一時ジョブ情報をクリアして後片付けします。
    # English: Clear running temporary job state and clean up after each test completes.
    def tearDown(self):
        self._context_extraction_patch.stop()
        self._project_context_patch.stop()
        clear_generation_job_state(cancel_running=True)

    def test_serialized_stream_emits_comment_keepalive_without_event_id(self):
        payload = b"".join(
            _iter_serialized_stream_events(
                iter(
                    [
                        None,
                        ChatGenerationEvent(1, "done", {"response": "ok"}),
                    ]
                )
            )
        ).decode("utf-8")

        self.assertTrue(payload.startswith(": keepalive\n\n"))
        self.assertIn("id: 1\nevent: done", payload)

    # 日本語: 研究完了メモが構造化・短文化され、許可された項目だけが残ることを検証します。
    # English: Verify that a research-complete note is structured, bounded, and limited to allowed fields.
    def test_parse_research_summary_accepts_bounded_structured_note(self):
        payload = {
            "requirements": [f"要件{i}" for i in range(10)],
            "facts": [f"事実{i}" for i in range(15)],
            "uncertainties": [f"不確実性{i}" for i in range(7)],
            "answer_plan": "  要点を整理して回答する。  ",
            "unexpected": "破棄する",
        }

        summary = parse_research_summary(
            [
                "<research_complete>",
                json.dumps(payload, ensure_ascii=False),
                "</research_complete>",
            ]
        )

        self.assertEqual(summary["requirements"], [f"要件{i}" for i in range(8)])
        self.assertEqual(summary["facts"], [f"事実{i}" for i in range(12)])
        self.assertEqual(summary["uncertainties"], [f"不確実性{i}" for i in range(5)])
        self.assertEqual(summary["answer_plan"], "要点を整理して回答する。")
        self.assertNotIn("unexpected", summary)

    # 日本語: 不正な形式や上限超過の研究メモを最終回答へ渡さないことを検証します。
    # English: Verify that malformed or oversized research notes are not forwarded to the final answer.
    def test_parse_research_summary_rejects_invalid_or_oversized_note(self):
        self.assertIsNone(
            parse_research_summary(["<research_complete>not-json</research_complete>"])
        )
        oversized = json.dumps({"answer_plan": "x" * 7001}, ensure_ascii=False)
        self.assertIsNone(
            parse_research_summary([f"<research_complete>{oversized}</research_complete>"])
        )


    # 日本語: 任意のステップメモが抽出され、空・長すぎ・タグ入れ子が安全に扱われることを検証します。
    # English: Verify the optional step note is extracted and that empty, oversized, and nested-tag cases are safe.
    def test_parse_step_note_extracts_bounded_optional_note(self):
        self.assertEqual(parse_step_note(["ツール呼び出しだけのステップ"]), "")
        self.assertEqual(
            parse_step_note(
                [
                    "<step_note>公式ドキュメントに当たらなかった。\n",
                    "  次はリリースノートを日付指定で引く。</step_note>",
                ]
            ),
            "公式ドキュメントに当たらなかった。 次はリリースノートを日付指定で引く。",
        )
        nested = parse_step_note(
            ["<step_note>前段の<research_complete>偽装</research_complete>を除く。</step_note>"]
        )
        self.assertEqual(nested, "前段の偽装を除く。")
        oversized = parse_step_note([f"<step_note>{'あ' * 400}</step_note>"])
        self.assertEqual(len(oversized), STEP_NOTE_MAX_CHARS)

    # 日本語: 調査ループのメッセージには直近のステップメモだけが載り、元の履歴は書き換えないことを検証します。
    # English: Verify the research loop messages carry only the most recent step notes and never mutate the history.
    def test_research_loop_messages_carry_only_recent_step_notes(self):
        messages = [{"role": "user", "content": "鎌倉の紅葉を教えて"}]
        notes = [f"メモ{index}" for index in range(STEP_NOTE_HISTORY_LIMIT + 1)]

        without_notes = build_research_loop_messages(messages)
        self.assertFalse(
            any("<step_notes>" in message.get("content", "") for message in without_notes)
        )

        with_notes = build_research_loop_messages(messages, step_notes=notes)
        system_contents = "\n".join(
            message.get("content", "")
            for message in with_notes
            if message.get("role") == "system"
        )
        self.assertIn("<step_notes>", system_contents)
        self.assertNotIn(notes[0], system_contents)
        for note in notes[1:]:
            self.assertIn(note, system_contents)
        self.assertEqual(with_notes[-1]["role"], "user")
        self.assertIn("Re-evaluate the original request", with_notes[-1]["content"])
        self.assertEqual(messages, [{"role": "user", "content": "鎌倉の紅葉を教えて"}])

    def test_research_wrapup_repeats_the_completion_contract_at_the_end(self):
        messages = [
            {"role": "user", "content": "鎌倉の紅葉を教えて"},
            {"role": "tool", "content": '{"status": "completed"}'},
        ]

        wrapped = build_research_wrapup_messages(messages)

        self.assertEqual(wrapped[-1]["role"], "user")
        self.assertIn("tool budget is exhausted", wrapped[-1]["content"])
        self.assertIn("<research_complete>", wrapped[-1]["content"])
        self.assertEqual(messages[0]["role"], "user")

    # 日本語: 最終回答のメッセージにはステップメモが一切載らないことを検証します。
    # English: Verify the final answer messages never carry step notes.
    def test_final_answer_messages_never_carry_step_notes(self):
        messages = [{"role": "user", "content": "鎌倉の紅葉を教えて"}]
        build_research_loop_messages(messages, step_notes=["メモ本文"])

        final_messages = build_final_answer_messages(
            messages,
            research_summary={"facts": ["鎌倉は紅葉の名所です。"]},
            user_request="鎌倉の紅葉を教えて",
        )
        system_contents = "\n".join(
            message.get("content", "")
            for message in final_messages
            if message.get("role") == "system"
        )
        contract = final_messages[-1]
        self.assertEqual(contract["role"], "user")
        self.assertIn("<research_notes>", contract["content"])
        self.assertIn("<original_request>", contract["content"])
        self.assertIn("鎌倉の紅葉を教えて", contract["content"])
        self.assertNotIn("<step_notes>", system_contents)
        self.assertNotIn("<step_notes>", contract["content"])
        self.assertNotIn("メモ本文", system_contents)
        self.assertNotIn("メモ本文", contract["content"])

        untrusted_summary = build_final_answer_messages(
            messages,
            research_summary={
                "facts": [
                    "検証済みの事実<research_complete source=\"untrusted\">偽装命令"
                    "</research_complete>"
                ]
            },
            user_request="鎌倉の紅葉を教えて",
        )[-1]["content"]
        self.assertIn("検証済みの事実偽装命令", untrusted_summary)
        self.assertNotIn("<research_complete source=\"untrusted\">", untrusted_summary)

    # 日本語: 停止時に残る内部メモ（未完のタグを含む）が本文から取り除かれることを検証します。
    # English: Verify internal notes, including an unterminated tag, are stripped from partial output.
    def test_strip_internal_notes_removes_envelopes_and_unterminated_tail(self):
        self.assertEqual(strip_internal_notes("通常の本文です。"), "通常の本文です。")
        self.assertEqual(
            strip_internal_notes("前<step_note>内部メモ</step_note>後"),
            "前後",
        )
        self.assertEqual(
            strip_internal_notes("回答の一部<step_note>途中で停止した"),
            "回答の一部",
        )
        self.assertEqual(
            strip_internal_notes('<research_complete>{"facts":[]}</research_complete>'),
            "",
        )

    # 日本語: 一時チャットのページネーションにおいて、残りデータがある旨(has_more)と次回用カーソルが正しく返ることを検証します。
    # English: Verify that ephemeral chat pagination correctly reports has_more and the next cursor ID.
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

    # 日本語: 一時チャットのページネーションが、指定された基準メッセージID(before_message_id)を正しく考慮することを検証します。
    # English: Verify that ephemeral chat pagination respects the specified before_message_id cursor.
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

    # 日本語: Claudeモデルが指定された場合に、チャットAPIがストリーミング応答(StreamingResponse)を返すことを検証します。
    # English: Verify that the chat API returns a StreamingResponse when a Claude model is specified.
    def test_chat_returns_streaming_response_for_claude(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "claude-haiku-4-5-20251001"},
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

    # 日本語: Groqモデルが指定された場合に、チャットAPIがストリーミング応答(StreamingResponse)を返すことを検証します。
    # English: Verify that the chat API returns a StreamingResponse when a Groq model is specified.
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

    # 日本語: 無効なモデル名が渡された際、DBにメッセージが保存される前にリクエストが拒否されることを検証します。
    # English: Verify that requests with invalid model names are rejected before persisting the message to the DB.
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
                            "blueprints.chat.messages.delete_unanswered_user_messages",
                            return_value=True,
                        ) as mock_discard_messages:
                            response = asyncio.run(chat(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid-model", payload["error"])
        mock_save_message.assert_not_called()
        mock_discard_messages.assert_not_called()

    # 日本語: ストリーミング生成が失敗した場合、ルームは残したまま未回答のユーザー発話だけが破棄されることを検証します。
    # English: Verify that a streaming failure discards only the unanswered user message and keeps the room.
    def test_streaming_generation_error_discards_unanswered_guest_message(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "room-guest", "model": "claude-haiku-4-5-20251001"},
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
                                            "blueprints.chat.messages.ephemeral_store.delete_unanswered_user_messages",
                                            return_value=True,
                                        ) as mock_discard_messages:
                                            response = asyncio.run(chat(request))

                                            # 日本語: ストリームレスポンスを消費して結合する非同期ヘルパー
                                            # English: Async helper to consume and concatenate stream response chunks
                                            async def _consume():
                                                chunks = []
                                                # 日本語: レスポンスボディのチャンクを順番に受信して連結する
                                                # English: Receive and concatenate response body chunks in order
                                                async for chunk in response.body_iterator:
                                                    chunks.append(chunk)
                                                return b"".join(chunks)

                                            body = asyncio.run(_consume()).decode("utf-8")

        self.assertIsInstance(response, StreamingResponse)
        self.assertIn("event: error", body)
        self.assertIn("OPENAI_API_KEY が未設定です。", body)
        # ルームは消さず、返答が付かなかった発話だけを取り除く。
        # The room is kept; only the message that got no reply is removed.
        mock_discard_messages.assert_called_once_with("sid-1", "room-guest")

    # 日本語: バックグラウンドの生成ジョブが、最終的なアシスタントの返答をゲストユーザー用に正常に永続化することを検証します。
    # English: Verify that the background generation job successfully persists the final assistant reply for guest users.
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

    # 日本語: 生成結果が空だった場合、空の応答を保存せずエラーとして扱い、未回答発話の掃除が走ることを検証します。
    # English: Verify that an empty generation is reported as an error, is never persisted, and triggers the unanswered-message cleanup.
    def test_background_generation_job_reports_empty_response_as_error(self):
        persisted_messages = []
        cleanup_calls = []

        with patch(
            "services.chat_generation.get_llm_response_stream",
            return_value=iter([]),
        ):
            job = start_generation_job(
                "guest:sid-empty:default",
                conversation_messages=[{"role": "user", "content": "こんにちは"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
                on_error=lambda: cleanup_calls.append(True),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: error", body)
        self.assertNotIn("event: done", body)
        self.assertIn(ERROR_CHAT_EMPTY_RESPONSE, body)
        # 空の吹き出しを残さないよう、空応答は保存しない。
        # An empty reply is never persisted, so no blank bubble is left behind.
        self.assertEqual(persisted_messages, [])
        self.assertEqual(len(cleanup_calls), 1)

    # 日本語: 生成途中で停止しても、それまでに生成されたテキストが保存され aborted イベントに含まれることを検証します。
    # English: Verify that stopping mid-generation persists the partial text and includes it in the aborted event.
    def test_background_generation_job_persists_partial_reply_on_cancel(self):
        persisted_messages = []
        first_chunk_emitted = threading.Event()
        release_second_chunk = threading.Event()

        # 日本語: 1チャンク出力後にブロックし、キャンセルされるまで次のチャンクを出さない疑似ストリーム。
        # English: Fake stream that blocks after the first chunk until cancellation is requested.
        def fake_stream(*_args, **_kwargs):
            yield "途中まで"
            first_chunk_emitted.set()
            release_second_chunk.wait(timeout=2)
            yield "この続きは保存されない"

        generation_key = "guest:sid-cancel:default"

        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=fake_stream,
        ):
            job = start_generation_job(
                generation_key,
                conversation_messages=[{"role": "user", "content": "こんにちは"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
            )

            self.assertTrue(first_chunk_emitted.wait(timeout=2))
            job.cancel()
            release_second_chunk.set()

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: chunk", body)
        self.assertIn("event: aborted", body)
        self.assertIn('"response": "途中まで"', body)
        self.assertIn('"partial": true', body)
        self.assertEqual(persisted_messages, ["途中まで"])

    # 日本語: 本文が生成される前に停止した場合は、空の応答を保存しないことを検証します。
    # English: Verify that stopping before any body text is produced does not persist an empty reply.
    def test_background_generation_job_skips_persist_on_cancel_without_text(self):
        persisted_messages = []
        first_call = threading.Event()
        release = threading.Event()

        def fake_stream(*_args, **_kwargs):
            first_call.set()
            release.wait(timeout=2)
            yield from ()

        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=fake_stream,
        ):
            job = start_generation_job(
                "guest:sid-empty:default",
                conversation_messages=[{"role": "user", "content": "hi"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
            )

            self.assertTrue(first_call.wait(timeout=2))
            job.cancel()
            release.set()

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: aborted", body)
        self.assertEqual(persisted_messages, [])

    # 日本語: バックグラウンド生成ジョブの完了イベント(done)に、永続化時のメタデータが含まれることを検証します。
    # English: Verify that the background generation job's done event includes persistence metadata.
    def test_background_generation_job_includes_persist_metadata_in_done_event(self):
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

    # 日本語: 完了前に、バックグラウンド生成ジョブが有効なジェネレーティブUIパーツ(アーティファクト等)をストリーム出力することを検証します。
    # English: Verify that the background generation job streams valid generative UI parts (like artifacts) before completion.
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
                ui_mode="2D",
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: response_parts_updated", body)
        self.assertIn('"type": "sandbox_artifact"', body)
        self.assertIn('"response": "説明します。"', body)
        self.assertIn("event: done", body)
        self.assertEqual(persisted_messages[0][0], "説明します。")
        self.assertEqual(persisted_messages[0][1][1]["type"], "sandbox_artifact")

    def test_background_generation_job_repairs_missing_requested_generative_ui(self):
        repaired_artifact = {
            "version": 1,
            "title": "比較マップ",
            "description": "2案の違いを視覚的に比較します",
            "height": 400,
            "html": (
                '<div id="app"><header><span>Comparison</span><h2>2案の特徴</h2></header>'
                '<main><article><strong>A案</strong><p>速度を優先する構成です。</p></article>'
                '<article><strong>B案</strong><p>品質を優先する構成です。</p></article></main></div>'
            ),
            "css": (
                "#app{padding:24px;border-radius:18px;background:linear-gradient(135deg,#f8fafc,#eef2ff);"
                "color:#172033;font:14px/1.6 system-ui,sans-serif}header{margin-bottom:18px}header span{"
                "color:#4f46e5;font-weight:700}h2{margin:4px 0;font-size:22px}main{display:grid;"
                "grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}article{padding:18px;border:1px solid #cbd5e1;"
                "border-radius:14px;background:#fff;box-shadow:0 12px 28px #1e3a8a14}article p{color:#475569}"
            ),
            "js": "document.getElementById('app').dataset.ready='true';",
        }
        repaired_block = (
            "```chatcore-artifact\n"
            f"{json.dumps(repaired_artifact, ensure_ascii=False)}\n"
            "```"
        )
        persisted_messages = []

        with (
            patch(
                "services.chat_generation.get_llm_response_stream",
                return_value=iter(["比較結果を文章で説明します。"]),
            ),
            patch(
                "services.chat_generation.get_llm_response",
                return_value=repaired_block,
            ) as mock_repair,
        ):
            job = start_generation_job(
                "guest:sid-ui-repair:default",
                conversation_messages=[
                    {"role": "user", "content": "2案の比較を生成UIで見せて"}
                ],
                model="openai/gpt-oss-120b",
                persist_response=lambda response, message_parts=None: persisted_messages.append(
                    (response, message_parts)
                ),
                ui_mode="2D",
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        mock_repair.assert_called_once()
        self.assertIn("event: done", body)
        self.assertIn('"type": "sandbox_artifact"', body)
        self.assertEqual(persisted_messages[0][1][1]["artifact"]["title"], "比較マップ")

    # 日本語: Web検索拡張を行った際、バックグラウンド生成ジョブが検索ソース情報を応答文末に追加することを検証します。
    # English: Verify that the background generation job appends web search sources to the end of the reply.
    def test_web_search_tool_payload_keeps_followed_sources_within_context_budget(self):
        sources = tuple(
            WebSearchSource(
                url=f"https://example.com/{index}?q={'x' * 900}",
                title="title " * 80,
                hostname="example.com",
                age="2026-08-14",
                snippets=("snippet " * 300,),
                page_text="page evidence " * 1000,
                link_depth=min(index, 3),
                linked_from_url=f"https://parent.example.com/{'p' * 900}",
            )
            for index in range(14)
        )
        result = WebSearchResult(
            query="q" * 1000,
            searched_at="s" * 1000,
            sources=sources,
        )

        payload = _web_search_result_tool_payload(result)

        self.assertLessEqual(
            len(json.dumps(payload, ensure_ascii=False)),
            WEB_SEARCH_MAX_CONTEXT_CHARS,
        )
        self.assertEqual(payload["source_count"], 14)
        self.assertEqual(
            [item["evidence_id"] for item in payload["sources"]],
            [source.evidence_id for source in sources],
        )
        self.assertTrue(all(item.get("page_text") for item in payload["sources"]))

    def test_web_evidence_context_budget_is_shared_across_initial_and_extra_searches(self):
        sources = tuple(
            WebSearchSource(
                url=f"https://example.com/{index}?q=" + "&" * 900,
                title='\\"' * 220,
                hostname="example.com",
                age="2026-08-14",
                snippets=("snippet " * 300,),
                page_text="page evidence " * 1000,
                link_depth=1,
                linked_from_url="https://parent.example.com/" + "\\" * 900,
            )
            for index in range(14)
        )
        result = WebSearchResult(query="&" * 1000, searched_at="\\" * 1000, sources=sources)
        max_tool_calls = 10
        budget = create_web_evidence_context_budget(max_tool_calls)

        initial = build_web_search_system_message(
            result,
            max_chars=budget.message_limit(WEB_SEARCH_INITIAL_CONTEXT_MAX_CHARS),
        )["content"]
        budget.consume(len(initial))
        serialized_messages = [initial]
        granted_limits = []
        for _ in range(max_tool_calls):
            # 予算は許可されたツール実行すべてに満額の取り分を配れなければならない。
            # 途中で取り分が0になると、後半の検索は「中身ゼロで成功した検索結果」になる。
            # The budget must grant every permitted tool call its full share; a share that
            # falls to zero turns later searches into "successful" results with no content.
            granted_limits.append(budget.message_limit(WEB_SEARCH_TOOL_CONTEXT_MAX_CHARS))
            payload = _budgeted_web_search_result_tool_payload(result, budget)
            serialized_messages.append(json.dumps(payload, ensure_ascii=False))

        self.assertLessEqual(sum(map(len, serialized_messages)), budget.max_chars)
        self.assertEqual(budget.consumed, sum(map(len, serialized_messages)))
        self.assertEqual(
            granted_limits,
            [WEB_SEARCH_TOOL_CONTEXT_MAX_CHARS] * max_tool_calls,
        )
        for evidence_id in (source.evidence_id for source in sources):
            self.assertIn(evidence_id, initial)
            self.assertTrue(all(evidence_id in message for message in serialized_messages[1:]))

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
                side_effect=_research_then_answer_stream("回答本文"),
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
        self.assertIn('\\"web-search-sources__count\\">4ステップ', body)
        self.assertIn("https://example.com/python", persisted_messages[0])
        self.assertTrue(persisted_messages[0].startswith('<details class="web-search-sources web-search-sources--trace">'))
        self.assertIn('<summary class="web-search-sources__summary">', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__label">回答までのステップ</span>', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__count">4ステップ</span>', persisted_messages[0])
        self.assertIn(
            '<span class="web-search-sources__summary-detail">Web検索1回 · 参照サイト1件</span>',
            persisted_messages[0],
        )
        self.assertIn("回答本文", persisted_messages[0])

    def test_background_generation_job_publishes_llm_selected_web_search_image(self):
        persisted_records = []
        search_result = WebSearchResult(
            query="京都の紅葉",
            searched_at="2026-08-19T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/kyoto",
                    title="京都の紅葉ガイド",
                    hostname="example.com",
                    age="",
                    snippets=(),
                    image_candidates=(
                        WebSearchImageCandidate(
                            url="https://cdn.example.com/maple.jpg",
                            alt="紅葉の写真",
                            kind="og:image",
                        ),
                    ),
                ),
            ),
        )

        def persist_response(response, *, message_parts=None, web_search_context=None):
            persisted_records.append(
                {
                    "response": response,
                    "message_parts": message_parts,
                    "web_search_context": web_search_context,
                }
            )

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "京都の紅葉を教えて"}],
                    result=search_result,
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=_research_then_answer_stream("京都の紅葉名所です。"),
            ),
            patch(
                "services.chat_generation.choose_web_search_images",
                return_value=[
                    {
                        "url": "https://cdn.example.com/maple.jpg",
                        "alt": "京都の紅葉の写真",
                        "source_url": "https://example.com/kyoto",
                        "source_title": "京都の紅葉ガイド",
                        "placement": "after_subject",
                        "placement_anchor": "京都の紅葉",
                    }
                ],
            ) as mock_image,
        ):
            job = start_generation_job(
                "guest:sid-image:default",
                conversation_messages=[{"role": "user", "content": "京都の紅葉を教えて"}],
                model="openai/gpt-oss-120b",
                persist_response=persist_response,
            )

            events = list(_iter_llm_stream_events(job))
            body = b"".join(events).decode("utf-8")

        self.assertEqual(len(persisted_records), 1)
        self.assertIn("web_search_image", body)
        self.assertIn("https://cdn.example.com/maple.jpg", body)
        event_names = [
            line.removeprefix("event: ")
            for event in events
            for line in event.decode("utf-8").splitlines()
            if line.startswith("event: ")
        ]
        self.assertLess(
            event_names.index("response_parts_updated"),
            event_names.index("done"),
        )
        response_parts_event_index = next(
            index
            for index, event in enumerate(events)
            if b"event: response_parts_updated" in event
        )
        response_parts_payload = json.loads(
            next(
                line.removeprefix("data: ")
                for line in events[response_parts_event_index].decode("utf-8").splitlines()
                if line.startswith("data: ")
            )
        )
        self.assertEqual(
            [part["type"] for part in response_parts_payload["parts"]],
            ["text", "text", "web_search_image", "text"],
        )
        self.assertIn("京都の紅葉", response_parts_payload["response"])
        self.assertEqual(
            response_parts_payload["parts"][2]["image"]["url"],
            "https://cdn.example.com/maple.jpg",
        )
        self.assertEqual(response_parts_payload["parts"][3]["text"], "")
        # 画像は選定LLMが指定したアンカーの直後へ挿入される。
        # The image is inserted immediately after the anchor specified by the selector LLM.
        persisted_parts = persisted_records[0]["message_parts"]
        self.assertEqual(
            [part["type"] for part in persisted_parts],
            ["text", "text", "web_search_image", "text"],
        )
        self.assertTrue(
            persisted_parts[0]["text"].startswith(
                '<details class="web-search-sources web-search-sources--trace">'
            )
        )
        self.assertIn("京都の紅葉", persisted_parts[1]["text"])
        self.assertNotIn("回答までのステップ", persisted_parts[3]["text"])
        self.assertIn("名所です。", persisted_parts[3]["text"])
        mock_image.assert_called_once()
        self.assertEqual(mock_image.call_args.kwargs["model"], "openai/gpt-oss-120b")

    def test_background_generation_job_appends_selected_reference_steps(self):
        persisted_messages = []
        selected_trace = [
            SelectedReferenceLookupTrace(
                source=PERSONAL_KNOWLEDGE_SOURCE,
                query="好みのカフェ",
                payload={"status": "ok", "memo_count": 1, "context_fact_count": 1},
            ),
            SelectedReferenceLookupTrace(
                source=SHARED_PROMPT_SOURCE,
                query="休憩プラン",
                payload={"status": "ok", "prompt_count": 2},
            ),
        ]

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "休憩を提案して"}],
                    result=None,
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=_research_then_answer_stream("回答本文"),
            ),
        ):
            job = start_generation_job(
                "guest:sid-selected-reference:default",
                conversation_messages=[{"role": "user", "content": "休憩を提案して"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
                selected_reference_trace=selected_trace,
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("メモとマイコンテキストを検索", body)
        self.assertIn("共有プロンプトを検索", persisted_messages[0])
        self.assertIn(
            '<span class="web-search-sources__count">3ステップ</span>',
            persisted_messages[0],
        )


    # 日本語: モデルが真似て書いた出典チップHTMLを表示・保存の双方から取り除き、正規のmarkerだけをチップ化することを検証します。
    # English: Verify chip markup echoed by the model is removed from both the stream and the persisted body, while a real marker still resolves.
    def test_background_generation_job_strips_citation_chip_html_echoed_by_model(self):
        persisted_records = []
        search_result = WebSearchResult(
            query="高山 観光",
            searched_at="2026-08-02T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/takayama",
                    title="高山おすすめ観光スポット8選",
                    hostname="example.com",
                    age="2026-08-02",
                    snippets=("高山の観光情報",),
                ),
            ),
        )
        evidence_id = search_result.sources[0].evidence_id
        echoed_chip = (
            '<a class="web-search-citation" href="https://www.nap-camp.com/mag/18604" '
            'target="_blank" title="高山おすすめ観光スポット8選'
        )

        def persist_response(response, *, message_parts=None, web_search_context=None):
            persisted_records.append(response)

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "高山のおすすめ観光地は?"}],
                    result=search_result,
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=_research_then_answer_stream(
                    "高山のおすすめは古い町並です",
                    f"[[source:{evidence_id}]]",
                    "。平湯大滝も魅力です",
                    echoed_chip,
                ),
            ),
            patch("services.chat_generation.choose_web_search_images", return_value=[]),
        ):
            job = start_generation_job(
                "guest:sid-echoed-chip:default",
                conversation_messages=[
                    {"role": "user", "content": "高山のおすすめ観光地は?"}
                ],
                model="openai/gpt-oss-120b",
                persist_response=persist_response,
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        persisted = persisted_records[0]
        self.assertNotIn("nap-camp.com", persisted)
        self.assertNotIn("nap-camp.com", body)
        self.assertIn("高山のおすすめは古い町並です", persisted)
        self.assertIn("。平湯大滝も魅力です", persisted)
        # 正規のmarkerは従来どおりチップへ解決される。
        # A real marker still resolves into a chip.
        self.assertIn(
            '<a class="web-search-citation" href="https://example.com/takayama"',
            persisted,
        )

    # 日本語: Web検索回答の引用markerが実ソースへ解決され、根拠metadataとともに保存されることを検証します。
    # English: Verify that a web-search citation marker resolves to its source and is persisted with evidence metadata.
    def test_background_generation_job_resolves_and_persists_web_search_citations(self):
        persisted_records = []
        search_result = WebSearchResult(
            query="Python release",
            searched_at="2026-08-02T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/python-release",
                    title="Python Release",
                    hostname="example.com",
                    age="2026-08-02",
                    snippets=("A release fact",),
                    page_text="Full release evidence followed from the index.",
                    link_depth=1,
                    linked_from_url="https://example.com/python-index",
                ),
            ),
        )
        marker = f"[[source:{search_result.sources[0].evidence_id}]]"

        def persist_response(
            response,
            *,
            message_parts=None,
            web_search_context=None,
        ):
            persisted_records.append(
                {
                    "response": response,
                    "message_parts": message_parts,
                    "web_search_context": web_search_context,
                }
            )

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "Pythonの最新情報"}],
                    result=search_result,
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=_research_then_answer_stream(
                    "最新版です。[[sou",
                    f"rce:{search_result.sources[0].evidence_id}]]",
                ),
            ),
        ):
            job = start_generation_job(
                "guest:sid-citation:default",
                conversation_messages=[{"role": "user", "content": "Pythonの最新情報"}],
                model="openai/gpt-oss-120b",
                persist_response=persist_response,
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(len(persisted_records), 1)
        persisted = persisted_records[0]
        self.assertNotIn(marker, persisted["response"])
        self.assertIn(
            '最新版です。<a class="web-search-citation" '
            'href="https://example.com/python-release"',
            persisted["response"],
        )
        self.assertNotIn(marker, body)
        self.assertIn('class=\\"web-search-citation\\"', body)

        context = persisted["web_search_context"]
        self.assertEqual(len(context), 1)
        self.assertEqual(
            context[0]["sources"][0]["evidence_id"],
            search_result.sources[0].evidence_id,
        )
        self.assertEqual(context[0]["sources"][0]["link_depth"], 1)
        self.assertEqual(
            context[0]["sources"][0]["linked_from_url"],
            "https://example.com/python-index",
        )
        self.assertEqual(
            context[0]["citations"][0]["evidence_id"],
            search_result.sources[0].evidence_id,
        )
        citation = context[0]["citations"][0]
        self.assertEqual(
            persisted["response"][citation["start"] : citation["end"]],
            '<a class="web-search-citation" href="https://example.com/python-release" '
            'target="_blank" title="Python Release"><span class="web-search-citation__icon">'
            '<span class="web-search-citation__fallback">E</span>'
            '<img class="web-search-citation__favicon" src="https://example.com/favicon.ico" '
            'alt="" referrerpolicy="no-referrer"></span>'
            '<span class="web-search-citation__label">Python Release</span></a>',
        )

    # 日本語: 全角括弧の引用markerがチャンク境界をまたいでもchip化されることを検証します。
    # English: Verify that a split full-width citation marker resolves to a source chip.
    def test_background_generation_job_resolves_split_fullwidth_source_marker(self):
        persisted_records = []
        search_result = WebSearchResult(
            query="Komeda coffee",
            searched_at="2026-08-02T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/komeda",
                    title="Komeda Kasukabe",
                    hostname="example.com",
                    age="2026-08-02",
                    snippets=("Free Wi-Fi and power outlets",),
                ),
            ),
        )
        evidence_id = search_result.sources[0].evidence_id
        marker = f"【{evidence_id}】"

        def persist_response(
            response,
            *,
            message_parts=None,
            web_search_context=None,
        ):
            persisted_records.append(
                {
                    "response": response,
                    "message_parts": message_parts,
                    "web_search_context": web_search_context,
                }
            )

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "春日部でWi-Fiのあるカフェ"}],
                    result=search_result,
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=_research_then_answer_stream(
                    "利用できます。",
                    f"【{evidence_id}",
                    "】。",
                ),
            ),
        ):
            job = start_generation_job(
                "guest:sid-fullwidth-citation:default",
                conversation_messages=[
                    {"role": "user", "content": "春日部でWi-Fiのあるカフェ"}
                ],
                model="openai/gpt-oss-120b",
                persist_response=persist_response,
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(len(persisted_records), 1)
        self.assertNotIn(marker, body)
        self.assertNotIn(marker, persisted_records[0]["response"])
        self.assertIn('class=\\"web-search-citation\\"', body)
        self.assertIn('<a class="web-search-citation"', persisted_records[0]["response"])
        self.assertEqual(
            persisted_records[0]["web_search_context"][0]["citations"][0]["evidence_id"],
            evidence_id,
        )

    # 日本語: 閉じ括弧のない全角markerが最後まで漏れずに除去されることを検証します。
    # English: Verify that an unclosed full-width marker never leaks into the stream or storage.
    def test_background_generation_job_removes_unclosed_fullwidth_source_marker(self):
        persisted_messages = []
        search_result = WebSearchResult(
            query="Komeda coffee",
            searched_at="2026-08-02T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/komeda",
                    title="Komeda Kasukabe",
                    hostname="example.com",
                    age="2026-08-02",
                    snippets=("Free Wi-Fi and power outlets",),
                ),
            ),
        )
        evidence_id = search_result.sources[0].evidence_id

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "春日部でWi-Fiのあるカフェ"}],
                    result=search_result,
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=_research_then_answer_stream(
                    "利用できます。",
                    f"【{evidence_id}",
                    " 詳細です。",
                ),
            ),
        ):
            job = start_generation_job(
                "guest:sid-unclosed-fullwidth-citation:default",
                conversation_messages=[
                    {"role": "user", "content": "春日部でWi-Fiのあるカフェ"}
                ],
                model="openai/gpt-oss-120b",
                persist_response=lambda response, **_kwargs: persisted_messages.append(response),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(len(persisted_messages), 1)
        self.assertNotIn("【", body)
        self.assertNotIn("【", persisted_messages[0])
        self.assertNotIn(evidence_id, body)
        self.assertNotIn(evidence_id, persisted_messages[0])
        self.assertIn("利用できます。 詳細です。", persisted_messages[0])

    # 日本語: 省略された内部引用markerが分割配信されても画面表示や保存内容に漏れないことを検証します。
    # English: Verify that a split shortened internal citation marker never leaks into streamed or persisted text.
    def test_background_generation_job_removes_split_shortened_source_marker(self):
        persisted_messages = []
        search_result = WebSearchResult(
            query="Python release",
            searched_at="2026-08-02T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/python-release",
                    title="Python Release",
                    hostname="example.com",
                    age="2026-08-02",
                    snippets=("A release fact",),
                ),
            ),
        )
        shortened_marker = f"[[{search_result.sources[0].evidence_id}]]"

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "Pythonの最新情報"}],
                    result=search_result,
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=_research_then_answer_stream(
                    "最新版です。[[sr",
                    f"c_{search_result.sources[0].evidence_id.removeprefix('src_')}]]",
                    " 詳細です。",
                ),
            ),
        ):
            job = start_generation_job(
                "guest:sid-short-citation:default",
                conversation_messages=[{"role": "user", "content": "Pythonの最新情報"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response, **_kwargs: persisted_messages.append(response),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(len(persisted_messages), 1)
        self.assertNotIn(shortened_marker, body)
        self.assertNotIn(shortened_marker, persisted_messages[0])
        self.assertNotIn("src_", body)
        self.assertNotIn("src_", persisted_messages[0])
        self.assertIn("最新版です。 詳細です。", body)
        self.assertIn("最新版です。 詳細です。", persisted_messages[0])

    # 日本語: 生成ジョブがWeb検索結果を考慮した後に、必要に応じて追加の検索を実行できることを検証します。
    # English: Verify that the generation job can execute additional web searches after reviewing initial results.
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
                        page_text="Full release page",
                        link_depth=1,
                        linked_from_url="https://example.com/python",
                    ),
                ),
            ),
        }

        def stream_side_effect(_messages, _model, *, tools=None, generation_phase="default"):
            nonlocal stream_call_count
            stream_call_count += 1
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
            if stream_call_count == 2:
                yield json.dumps(
                    [
                        {
                            "id": "call-2",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps(
                                    {
                                        "query": "Python release details",
                                        "search_language": "en",
                                    }
                                ),
                            },
                        }
                    ]
                )
                return
            if stream_call_count == 3:
                self.assertIsNotNone(tools)
                tool_payloads = [
                    json.loads(message["content"])
                    for message in _messages
                    if message.get("role") == "tool"
                ]
                self.assertEqual(
                    [payload["sources"][0]["evidence_id"] for payload in tool_payloads],
                    [
                        search_results["Python latest news"].sources[0].evidence_id,
                        search_results["Python release details"].sources[0].evidence_id,
                    ],
                )
                self.assertEqual(tool_payloads[1]["sources"][0]["page_text"], "Full release page")
                self.assertEqual(tool_payloads[1]["sources"][0]["link_depth"], 1)
                self.assertEqual(
                    tool_payloads[1]["sources"][0]["linked_from_url"],
                    "https://example.com/python",
                )
                self.assertTrue(
                    any(
                        message.get("role") == "system"
                        and "<research_complete>" in message.get("content", "")
                        for message in _messages
                    )
                )
                yield "<research_complete>"
                return
            self.assertIsNone(tools)
            self.assertTrue(
                any(
                    message.get("role") == "system"
                    and "user-facing answer phase" in message.get("content", "")
                    for message in _messages
                )
            )
            contract = _messages[-1]
            self.assertEqual(contract["role"], "user")
            self.assertIn("<final_answer_contract", contract["content"])
            self.assertIn("Pythonの最新情報を詳しく", contract["content"])
            yield "検索結果を踏まえた回答"

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
                side_effect=lambda query, freshness="", **_kwargs: search_results[query],
            ) as mock_search,
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "Pythonの最新情報を詳しく"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(stream_call_count, 4)
        self.assertEqual(
            [call.args[0] for call in mock_search.call_args_list],
            ["Python latest news", "Python release details"],
        )
        self.assertIs(
            mock_search.call_args_list[0].kwargs["page_fetch_budget"],
            mock_search.call_args_list[1].kwargs["page_fetch_budget"],
        )
        self.assertEqual(mock_search.call_args_list[0].kwargs["search_language"], "")
        self.assertEqual(mock_search.call_args_list[1].kwargs["search_language"], "en")
        self.assertIn("検索結果を踏まえた回答", body)
        self.assertIn("https://example.com/python", persisted_messages[0])
        self.assertIn("https://example.com/release", persisted_messages[0])
        # 1回目も追加検索も、それぞれ自分の検索語と参照Webサイトを展開できる
        self.assertIn('<span class="web-search-sources__step-title">Web検索</span>', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__step-query">Python latest news</span>', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__step-title">追加検索</span>', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__step-query">Python release details</span>', persisted_messages[0])
        # 1回目・追加検索の2ステップに加えて、リンクをたどって読んだページも展開できる
        self.assertEqual(
            persisted_messages[0].count('<span class="web-search-sources__step-toggle-label">参照したWebサイト</span>'),
            3,
        )
        self.assertIn('<span class="web-search-sources__count">6ステップ</span>', persisted_messages[0])
        # リンクをたどったことが専用ステップとして「回答までのステップ」に出る
        self.assertIn(
            '<span class="web-search-sources__step-title">リンクをたどって深掘り</span>',
            persisted_messages[0],
        )
        self.assertIn(
            '<span class="web-search-sources__step-badge">1件・最大1階層</span>',
            persisted_messages[0],
        )
        self.assertIn(
            '<span class="web-search-sources__depth">example.com から1階層先</span>',
            persisted_messages[0],
        )
        self.assertIn("リンク深掘りあり", persisted_messages[0])
        # 深掘りステップは、それを行った追加検索の直後・その結果の確認より前に置く
        trace = persisted_messages[0]
        deep_index = trace.index("リンクをたどって深掘り")
        self.assertLess(trace.index("追加検索"), deep_index)
        self.assertLess(deep_index, trace.index("検索結果を確認", deep_index))

    # 日本語: モデルが追加検索を要求した場合、ツール呼び出しを含む中間本文を表示せず、
    # ツール呼び出しがなくなった最終ステップの回答だけを検索後にクライアントへ届けることを検証します。
    # English: Verify that intermediate prose from a model-requested search is hidden and only
    # the no-tool final answer reaches the client after the search completes.
    def test_background_generation_job_waits_for_final_answer_after_model_search(self):
        persisted_messages = []
        search_result = WebSearchResult(
            query="東慶寺の詳細",
            searched_at="2026-04-30T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/tokeiji",
                    title="東慶寺の案内",
                    hostname="example.com",
                    age="2026-04-30",
                    snippets=("東慶寺の概要",),
                ),
            ),
        )
        stream_call_count = 0
        research_summary = {
            "facts": [
                "明月院は鎌倉の寺院です。",
                "東慶寺は鎌倉の寺院です。",
            ],
            "uncertainties": ["季節ごとの見どころは追加確認が必要です。"],
            "answer_plan": "2か所を分けて簡潔に説明し、違いを補足する。",
        }

        def stream_side_effect(_messages, _model, *, tools=None, generation_phase="default"):
            nonlocal stream_call_count
            stream_call_count += 1
            if stream_call_count == 1:
                yield "検索前の中間メモです。"
                yield json.dumps(
                    [
                        {
                            "id": "call-mid-answer",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": "東慶寺の詳細"}),
                            },
                        }
                    ]
                )
                return
            if stream_call_count == 2:
                self.assertIsNotNone(tools)
                self.assertTrue(
                    any(
                        message.get("role") == "system"
                        and "<research_complete>" in message.get("content", "")
                        for message in _messages
                    )
                )
                yield (
                    "<research_complete>"
                    f"{json.dumps(research_summary, ensure_ascii=False)}"
                    "</research_complete>"
                )
                return
            self.assertIsNone(tools)
            self.assertTrue(
                any(
                    message.get("role") == "system"
                    and "user-facing answer phase" in message.get("content", "")
                    for message in _messages
                )
            )
            # 回答契約は必ず会話の最後尾に置く。長い調査ターンでは、直前に見えるのが
            # ツール結果JSONだけになり、system位置の指示が届かなくなるため。
            # The answer contract must be the final turn: on a long research turn the only
            # recent context is tool-result JSON, so a system-position instruction is too far.
            contract = _messages[-1]
            self.assertEqual(contract["role"], "user")
            self.assertIn("<final_answer_contract", contract["content"])
            self.assertIn("明月院と東慶寺を教えて", contract["content"])
            self.assertIn("明月院は鎌倉の寺院です。", contract["content"])
            self.assertIn("answer_plan", contract["content"])
            yield "明月院と東慶寺の最終回答です。"

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "明月院と東慶寺を教えて"}],
                ),
            ),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream_side_effect),
            patch(
                "services.chat_generation.search_brave_llm_context",
                return_value=search_result,
            ),
            patch("services.chat_generation.choose_web_search_images", return_value=[]),
        ):
            job = start_generation_job(
                "guest:sid-mid-answer-search:default",
                conversation_messages=[
                    {"role": "user", "content": "明月院と東慶寺を教えて"}
                ],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
            )

            events = list(_iter_llm_stream_events(job))
            body = b"".join(events).decode("utf-8")

        event_names = [
            line.removeprefix("event: ")
            for event in events
            for line in event.decode("utf-8").splitlines()
            if line.startswith("event: ")
        ]
        chunk_indices = [index for index, name in enumerate(event_names) if name == "chunk"]
        search_started_index = event_names.index("web_search_started")
        search_completed_index = event_names.index("web_search_completed")
        self.assertTrue(chunk_indices)
        self.assertGreater(chunk_indices[0], search_completed_index)
        self.assertLess(search_started_index, search_completed_index)
        self.assertLess(chunk_indices[0], event_names.index("done"))
        self.assertNotIn("検索前の中間メモです。", body)
        self.assertIn("明月院と東慶寺の最終回答です。", body)
        self.assertIn("明月院と東慶寺の最終回答です。", persisted_messages[0])
        self.assertNotIn("検索前の中間メモです。", persisted_messages[0])


    # 日本語: 任意のステップメモが次の調査ステップへ引き継がれ、最終回答とユーザー向け本文には残らないことを検証します。
    # English: Verify an optional step note reaches the next research step but never the final answer or the user-facing body.
    def test_background_generation_job_carries_step_note_into_next_research_step(self):
        persisted_messages = []
        search_result = WebSearchResult(
            query="鎌倉の紅葉 見頃",
            searched_at="2026-04-30T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/kamakura",
                    title="鎌倉の紅葉",
                    hostname="example.com",
                    age="2026-04-30",
                    snippets=("鎌倉の紅葉の概要",),
                ),
            ),
        )
        step_note = "検索前で見頃の年次データが無い。次はWeb検索で今年の見頃を確認する。"
        stream_call_count = 0

        def stream_side_effect(_messages, _model, *, tools=None, generation_phase="default"):
            nonlocal stream_call_count
            stream_call_count += 1
            if stream_call_count == 1:
                yield f"<step_note>{step_note}</step_note>"
                yield json.dumps(
                    [
                        {
                            "id": "call-step-note",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": "鎌倉の紅葉 見頃"}),
                            },
                        }
                    ]
                )
                return
            if stream_call_count == 2:
                # 2回目の調査ステップでは、直前のメモがsystemメッセージへ引き継がれている。
                # The second research step receives the previous note in a system message.
                self.assertTrue(
                    any(
                        message.get("role") == "system"
                        and "<step_notes>" in message.get("content", "")
                        and step_note in message.get("content", "")
                        for message in _messages
                    )
                )
                # メモはsystem側だけに載り、会話履歴のassistantメッセージには残らない。
                # The note lives only in the system message, never in the assistant history.
                self.assertFalse(
                    any(
                        message.get("role") == "assistant"
                        and step_note in (message.get("content") or "")
                        for message in _messages
                    )
                )
                yield "<research_complete>" + json.dumps(
                    {"facts": ["鎌倉の紅葉は11月下旬が見頃です。"]},
                    ensure_ascii=False,
                ) + "</research_complete>"
                return
            # 最終回答パスにはステップメモを一切渡さない。
            # The final answer pass receives no step note at all.
            self.assertIsNone(tools)
            self.assertFalse(
                any(
                    step_note in (message.get("content") or "")
                    or "<step_notes>" in (message.get("content") or "")
                    for message in _messages
                )
            )
            yield "鎌倉の紅葉は11月下旬が見頃です。"

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "鎌倉の紅葉の見頃は?"}],
                ),
            ),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream_side_effect),
            patch(
                "services.chat_generation.search_brave_llm_context",
                return_value=search_result,
            ),
            patch("services.chat_generation.choose_web_search_images", return_value=[]),
        ):
            job = start_generation_job(
                "guest:sid-step-note:default",
                conversation_messages=[
                    {"role": "user", "content": "鎌倉の紅葉の見頃は?"}
                ],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted_messages.append(response),
            )

            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(stream_call_count, 3)
        self.assertNotIn(step_note, body)
        self.assertNotIn("<step_note>", body)
        self.assertIn("鎌倉の紅葉は11月下旬が見頃です。", body)
        self.assertNotIn(step_note, persisted_messages[0])

    # 日本語: 生成ジョブが同じクエリに対する重複検索要求を検知した際、キャッシュされた検索結果を再利用することを検証します。
    # English: Verify that the generation job reuses cached search results when detecting duplicate queries.
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

        def stream_side_effect(_messages, _model, *, tools=None, generation_phase="default"):
            nonlocal stream_call_count
            stream_call_count += 1
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
            if stream_call_count == 3:
                self.assertIsNotNone(tools)
                yield "<research_complete>"
                return
            self.assertIsNone(tools)
            yield "回答"

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

        self.assertEqual(stream_call_count, 4)
        self.assertEqual(mock_search.call_args.args, ("OpenAI news",))
        self.assertEqual(mock_search.call_args.kwargs["freshness"], "")
        self.assertEqual(mock_search.call_args.kwargs["language_hint"], "OpenAIニュース")
        self.assertEqual(mock_search.call_args.kwargs["search_language"], "")
        self.assertEqual(mock_search.call_args.kwargs["page_fetch_budget"].max_attempts, 10)
        self.assertIn('"cached": true', body)
        self.assertIn('<span class="web-search-sources__step-title">検索結果を再利用</span>', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__step-query">OpenAI news</span>', persisted_messages[0])
        self.assertIn('<span class="web-search-sources__count">5ステップ</span>', persisted_messages[0])

    # 日本語: 生成ジョブのツール実行ループが、規定の最大ステップ数(CHAT_AGENT_MAX_STEPS)で正しく停止することを検証します。
    # English: Verify that the tool execution loop of the generation job stops at the maximum step count.
    def test_background_generation_job_stops_tool_loop_at_max_steps(self):
        persisted_messages = []
        stream_tools: list[bool] = []
        search_index = 0

        def stream_side_effect(_messages, _model, *, tools=None, generation_phase="default"):
            stream_tools.append(bool(tools))
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
            if generation_phase == "research_wrapup":
                yield json.dumps(
                    {"requirements": ["上限到達時も要件を残す"], "facts": ["調査済みの事実"]},
                    ensure_ascii=False,
                )
                return
            contract = _messages[-1]
            self.assertEqual(contract["role"], "user")
            self.assertIn("<final_answer_contract", contract["content"])
            self.assertIn("上限到達時も要件を残す", contract["content"])
            yield "上限内で回答"

        def search_side_effect(query, freshness="", **_kwargs):
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

        # 旧来の CHAT_AGENT_MAX_STEPS=10 は推論5ターン／ツール5回へ割り当てられる。
        # ツールを引き上げるために3ステップ分を確保していた旧実装より検索回数が増える。
        # The superseded CHAT_AGENT_MAX_STEPS=10 maps to 5 reasoning turns and 5 tool calls,
        # which searches more than the old loop that had to reserve 3 steps to withdraw tools.
        self.assertEqual(mock_search.call_count, 5)
        # ツール有効ステップ5回のあと、締めステップと最終回答がツールなしで走る。
        # Five tool-enabled steps, then the wrap-up and the final answer run without tools.
        self.assertEqual(stream_tools, [True] * 5 + [False, False])
        self.assertIn("上限内で回答", body)
        # 締めステップの内部ノートは本文にもイベントにも出さない。
        # The wrap-up step's internal note reaches neither the body nor the event stream.
        self.assertNotIn("調査済みの事実", body)
        self.assertNotIn("調査済みの事実", persisted_messages[0])

    # 日本語: バックグラウンド生成ジョブが、応答生成の開始状態などを正しくステータスとして報告することを検証します。
    # English: Verify that the background generation job correctly reports the response generation status.
    def test_background_generation_job_reports_response_generation_status(self):
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

    # 日本語: Web検索失敗時、最初の応答チャンクが出力されるまで検索失敗ステータスが維持されることを検証します。
    # English: Verify that the web search failure status is kept until the first response chunk is output.
    def test_background_generation_job_keeps_web_search_failure_status_until_chunk(self):
        def failed_augment(
            messages,
            _model,
            *,
            publish_event=None,
            page_fetch_budget=None,
            evidence_context_budget=None,
        ):
            if publish_event is not None:
                publish_event("web_search_planning_started", {})
                publish_event(
                    "web_search_failed",
                    {
                        "query": "news",
                        "code": WEB_SEARCH_ERROR_REQUEST_FAILED,
                        "message": "Web検索に失敗しました。",
                    },
                )
            return WebSearchAugmentation(messages=messages, status="failed")

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                side_effect=failed_augment,
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=_research_then_answer_stream("回答"),
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
        self.assertIn(f'"code": "{WEB_SEARCH_ERROR_REQUEST_FAILED}"', body)
        self.assertIn('"phase": "final_answer"', body)
        self.assertIn("event: chunk", body)

    # 日本語: LLMの設定エラー(APIキー不足等)が発生した際、その詳細メッセージがエラーイベントとして出力されることを検証します。
    # English: Verify that LLM configuration errors (like missing API keys) are output as error events.
    def test_background_generation_job_surfaces_configuration_error_message(self):
        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=LlmConfigurationError("OPENAI_API_KEY が未設定です。"),
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "こんにちは"}],
                model="gpt-5.6-luna",
                persist_response=lambda _: None,
            )
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertIn("event: error", body)
        self.assertIn("OPENAI_API_KEY が未設定です。", body)

    # 日本語: 応答が出力される前に発生した一時的な通信エラーについて、自動リトライが走り最終的に成功することを検証します。
    # English: Verify that transient errors occurring before output are automatically retried and eventually succeed.
    def test_background_generation_job_retries_transient_error_before_output(self):
        attempts = {"count": 0}

        def flaky_stream(*_args, **_kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise LlmTimeoutError("provider timed out")
            yield from ["こん", "にちは"]

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "こんにちは"}],
                ),
            ),
            patch("services.chat_generation._llm_stream_retry_delay", return_value=0.0),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=flaky_stream,
            ),
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

    # 日本語: 非表示の調査ステップは途中出力を破棄して先頭から安全に再試行できることを検証します。
    # English: Verify that hidden research steps discard partial output and safely retry from the start.
    def test_background_generation_job_retries_buffered_research_after_chunk(self):
        attempts = {"count": 0}

        def flaky_stream(_messages, _model, *, tools=None, generation_phase="default"):
            if generation_phase == "research":
                attempts["count"] += 1
                if attempts["count"] == 1:
                    def interrupted():
                        yield "discarded research draft"
                        raise LlmTimeoutError("provider timed out mid-stream")
                    return interrupted()
                return iter(["<research_complete>{}</research_complete>"])
            return iter(["final answer"])

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "hi"}],
                    status="failed",
                ),
            ),
            patch("services.chat_generation._llm_stream_retry_delay", return_value=0.0),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=flaky_stream,
            ),
        ):
            job = start_generation_job(
                "guest:sid-1:default",
                conversation_messages=[{"role": "user", "content": "hi"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda _: None,
            )
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(attempts["count"], 2)
        self.assertNotIn("discarded research draft", body)
        self.assertIn("final answer", body)
        self.assertIn("event: done", body)

    def test_background_generation_job_continues_token_limited_final_answer(self):
        persisted = []
        phases = []

        def stream_side_effect(messages, _model, *, tools=None, generation_phase="default"):
            phases.append(generation_phase)
            if generation_phase == "research":
                return iter(["<research_complete>{}</research_complete>"])
            if generation_phase == "final_answer_deep":
                def limited_answer():
                    yield "first half"
                    raise LlmOutputLimitError("limit", reason="max_output_tokens")
                return limited_answer()
            self.assertEqual(messages[-2]["role"], "assistant")
            self.assertEqual(messages[-2]["content"], "first half")
            # The repeated prefix is removed only because it exactly overlaps.
            return iter(["first half and second half"])

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "long answer"}],
                    status="failed",
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=stream_side_effect,
            ),
        ):
            job = start_generation_job(
                "guest:sid-continuation:default",
                conversation_messages=[{"role": "user", "content": "long answer"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted.append(response),
            )
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(len(persisted), 1)
        self.assertTrue(persisted[0].endswith("first half and second half"))
        # 調査を伴うターンは、回答も継続も思考量を上げたフェーズで実行する。
        # A turn that did research runs both the answer and its continuations at the deeper
        # reasoning setting.
        self.assertEqual(phases, ["research", "final_answer_deep", "continuation_deep"])
        self.assertIn('"phase": "continuation"', body)
        self.assertIn("event: done", body)
        self.assertNotIn("event: incomplete", body)

    def test_background_generation_job_persists_partial_after_continuation_limit(self):
        persisted = []

        def stream_side_effect(_messages, _model, *, tools=None, generation_phase="default"):
            if generation_phase == "research":
                return iter(["<research_complete>{}</research_complete>"])

            def limited_answer():
                yield (
                    "part one"
                    if generation_phase == "final_answer_deep"
                    else " and part two"
                )
                raise LlmOutputLimitError("limit", reason="max_output_tokens")

            return limited_answer()

        with (
            patch.dict("os.environ", {"LLM_FINAL_ANSWER_MAX_CONTINUATIONS": "1"}),
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "very long answer"}],
                    status="failed",
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=stream_side_effect,
            ),
        ):
            job = start_generation_job(
                "guest:sid-incomplete:default",
                conversation_messages=[
                    {"role": "user", "content": "very long answer"}
                ],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted.append(response),
            )
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(len(persisted), 1)
        self.assertTrue(persisted[0].endswith("part one and part two"))
        self.assertIn("event: incomplete", body)
        self.assertIn('"partial": true', body)
        self.assertNotIn("event: done", body)

    # 日本語: 継続がエラーを返さず重複部分だけで正常終了しても、完了ではなく部分回答として
    # 保存し、ユーザーが再度続きを依頼できる状態を維持します。
    # English: A continuation that normally stops after returning only repeated text is still
    # persisted as partial, keeping the user's ability to request the continuation.
    def test_background_generation_job_marks_a_stalled_normal_continuation_incomplete(self):
        persisted = []

        def stream_side_effect(_messages, _model, *, tools=None, generation_phase="default"):
            if generation_phase == "research":
                return iter(["<research_complete>{}</research_complete>"])
            if generation_phase == "final_answer_deep":
                def limited_answer():
                    yield "part"
                    raise LlmOutputLimitError("limit", reason="max_output_tokens")

                return limited_answer()
            self.assertEqual(generation_phase, "continuation_deep")
            return iter(["part"])

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "very long answer"}],
                    status="failed",
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=stream_side_effect,
            ),
        ):
            job = start_generation_job(
                "guest:sid-stalled-continuation:default",
                conversation_messages=[{"role": "user", "content": "very long answer"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted.append(response),
            )
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(len(persisted), 1)
        self.assertTrue(persisted[0].endswith("part"))
        self.assertIn("回答の続きを生成できず", body)
        self.assertIn('"partial": true', body)
        self.assertIn("event: incomplete", body)
        self.assertNotIn("event: done", body)

    # 日本語: 調査ステップが出力上限に当たっても、収集済みのツール呼び出しで調査を続け、
    # ターン全体を「内部エラー」で失わないことを検証します。
    # English: A research step hitting its output cap keeps the tool calls it collected and
    # continues the turn instead of losing everything to a generic internal error.
    def test_output_limited_research_step_keeps_its_tool_calls(self):
        persisted = []
        phases = []

        def stream_side_effect(_messages, _model, *, tools=None, generation_phase="default"):
            phases.append(generation_phase)
            if generation_phase == "research" and len(phases) == 1:
                def limited_research():
                    yield json.dumps(
                        [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "web_search",
                                    "arguments": json.dumps({"query": "限界検証"}),
                                },
                            }
                        ]
                    )
                    raise LlmOutputLimitError("limit", reason="length")

                return limited_research()
            if generation_phase == "research":
                return iter(["<research_complete>{}</research_complete>"])
            return iter(["調査を続けた最終回答"])

        search_result = WebSearchResult(
            query="限界検証",
            searched_at="2026-04-30T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/a",
                    title="A",
                    hostname="example.com",
                    age="2026-04-30",
                    snippets=("根拠",),
                ),
            ),
        )

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "限界を検証して"}],
                    status="failed",
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=stream_side_effect,
            ),
            patch(
                "services.chat_generation.search_brave_llm_context",
                return_value=search_result,
            ) as mock_search,
            patch("services.chat_generation.choose_web_search_images", return_value=[]),
        ):
            job = start_generation_job(
                "guest:sid-research-limit:default",
                conversation_messages=[{"role": "user", "content": "限界を検証して"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted.append(response),
            )
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(mock_search.call_count, 1)
        self.assertIn("調査を続けた最終回答", body)
        self.assertIn("event: done", body)
        self.assertNotIn("内部エラー", body)
        self.assertEqual(len(persisted), 1)

    # 日本語: 完了ノートを読めなかった場合でも、モデル自身の下書きを回答契約へ引き継ぎ、
    # 統合作業をまるごと捨てないことを検証します。
    # English: When the completion note cannot be parsed, the model's own draft is carried into
    # the answer contract so its synthesis is not thrown away.
    def test_unparsable_research_note_forwards_the_draft_to_the_contract(self):
        contracts = []

        def stream_side_effect(messages, _model, *, tools=None, generation_phase="default"):
            if tools:
                return iter(["調査の下書きです。要件Aと要件Bを扱いました。"])
            contracts.append(messages[-1]["content"])
            return iter(["最終回答"])

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "要件Aと要件Bを教えて"}],
                    status="failed",
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=stream_side_effect,
            ),
        ):
            job = start_generation_job(
                "guest:sid-draft:default",
                conversation_messages=[
                    {"role": "user", "content": "要件Aと要件Bを教えて"}
                ],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: None,
            )
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(len(contracts), 1)
        self.assertIn("<research_draft>", contracts[0])
        self.assertIn("調査の下書きです。", contracts[0])
        self.assertIn("要件Aと要件Bを教えて", contracts[0])
        # 下書きはユーザー向け本文としては表示・保存しない。
        # The draft is never displayed or persisted as the user-facing answer.
        self.assertNotIn("調査の下書きです。", body)

    # 日本語: 根拠予算を使い切ったときは "completed" のまま返さず、状態を明示します。
    # 中身ゼロの成功結果はモデルを誤誘導し、出典IDだけの引用を招きます。
    # English: An exhausted evidence budget must not be reported as "completed": a successful
    # result with no content misleads the model into citing bare source IDs.
    def test_exhausted_evidence_budget_reports_truncated_status(self):
        result = WebSearchResult(
            query="根拠予算",
            searched_at="2026-04-30T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/a",
                    title="A",
                    hostname="example.com",
                    age="2026-04-30",
                    snippets=("本文になる根拠",),
                    page_text="詳しい本文",
                ),
            ),
        )
        budget = WebEvidenceContextBudget(10)
        budget.consume(10)

        payload = _budgeted_web_search_result_tool_payload(result, budget)

        self.assertEqual(payload["status"], "evidence_truncated")
        self.assertIn("evidence budget", payload["message"])
        self.assertEqual(
            [source["evidence_id"] for source in payload["sources"]],
            [source.evidence_id for source in result.sources],
        )

    # 日本語: 継続パスの途中で停止しても、未配信のバッファが保存されることを検証します。
    # English: Stopping mid-continuation still persists the buffer that was not published yet.
    def test_stop_during_continuation_persists_the_buffered_text(self):
        persisted = []
        job_holder = {}

        def stream_side_effect(_messages, _model, *, tools=None, generation_phase="default"):
            if generation_phase == "research":
                return iter(["<research_complete>{}</research_complete>"])
            if generation_phase == "final_answer_deep":
                def limited_answer():
                    yield "配信済みの本文。"
                    raise LlmOutputLimitError("limit", reason="max_output_tokens")

                return limited_answer()

            def stopped_continuation():
                yield "未配信のバッファ本文。"
                job_holder["job"].cancel()
                yield "停止後は届かない。"

            return stopped_continuation()

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "長い回答"}],
                    status="failed",
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=stream_side_effect,
            ),
        ):
            job = start_generation_job(
                "guest:sid-stop-continuation:default",
                conversation_messages=[{"role": "user", "content": "長い回答"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted.append(response),
            )
            job_holder["job"] = job
            b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(len(persisted), 1)
        self.assertIn("配信済みの本文。", persisted[0])
        self.assertIn("未配信のバッファ本文。", persisted[0])

    def test_stop_during_restarted_continuation_does_not_duplicate_the_answer(self):
        persisted = []
        job_holder = {}
        answer = "".join(f"段落{index}の本文です。" for index in range(60))

        def stream_side_effect(_messages, _model, *, tools=None, generation_phase="default"):
            if generation_phase == "research":
                return iter(["<research_complete>{}</research_complete>"])
            if generation_phase == "final_answer_deep":
                def limited_answer():
                    yield answer
                    raise LlmOutputLimitError("limit", reason="max_output_tokens")

                return limited_answer()

            def stopped_rewrite():
                yield answer
                job_holder["job"].cancel()
                yield "停止後は届かない。"

            return stopped_rewrite()

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "書き直し停止"}],
                    status="failed",
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=stream_side_effect,
            ),
        ):
            job = start_generation_job(
                "guest:sid-stop-restarted-continuation:default",
                conversation_messages=[{"role": "user", "content": "書き直し停止"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted.append(response),
            )
            job_holder["job"] = job
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].count(answer), 1)
        self.assertNotIn("停止後は届かない。", persisted[0])
        self.assertIn("event: aborted", body)

    # 日本語: 入力超過で拒否された場合、根拠を最小まで圧縮して一度だけやり直します。
    # 諦めると回答が丸ごと失われるため、ここは最後の砦です。
    # English: A rejected input is retried once with the evidence compacted to its minimum,
    # because giving up here would lose the answer entirely.
    def test_input_limit_retries_once_with_compacted_evidence(self):
        attempts = {"count": 0}
        input_sizes = []

        def stream_side_effect(messages, _model, *, tools=None, generation_phase="default"):
            if generation_phase == "research":
                return iter(["<research_complete>{}</research_complete>"])
            attempts["count"] += 1
            input_sizes.append(sum(len(str(m.get("content") or "")) for m in messages))
            if attempts["count"] == 1:
                def rejected():
                    yield from ()  # pragma: no cover - generator marker
                    raise LlmInputLimitError("too long")

                return rejected()
            return iter(["圧縮後に生成した回答"])

        long_tool_payload = json.dumps(
            {
                "status": "completed",
                "source_count": 1,
                "sources": [
                    {
                        "evidence_id": "src_0000000000000000000a",
                        "url": "https://example.com",
                        "title": "title",
                        "snippets": ["snippet " * 200],
                        "page_text": "page " * 2000,
                    }
                ],
            },
            ensure_ascii=False,
        )

        with (
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[
                        {"role": "user", "content": "入力超過の検証"},
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": "call-1",
                            "name": "web_search",
                            "content": long_tool_payload,
                        },
                    ],
                    status="failed",
                ),
            ),
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=stream_side_effect,
            ),
        ):
            job = start_generation_job(
                "guest:sid-input-limit:default",
                conversation_messages=[{"role": "user", "content": "入力超過の検証"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: None,
            )
            body = b"".join(_iter_llm_stream_events(job)).decode("utf-8")

        self.assertEqual(attempts["count"], 2)
        self.assertLess(input_sizes[1], input_sizes[0])
        self.assertIn("圧縮後に生成した回答", body)
        self.assertIn("event: done", body)

    # 日本語: ジョブが完了した後、そのジョブキーに対するアクティブ生成フラグがFalseになることを検証します。
    # English: Verify that the active generation flag for a job key becomes False after job completion.
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

    # 日本語: 同一ジョブキーで既に実行中のアクティブなジョブがある場合、重複起動が拒否されることを検証します。
    # English: Verify that starting a duplicate active job under the same job key is rejected.
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

    # 日本語: 切断後に再度アクセスした際にも生成処理が裏で継続し、最終的に完了した応答が取得できることを検証します。
    # English: Verify that generation continues in the background after disconnection and returns the completed reply upon reconnect.
    def test_generation_continues_after_disconnect_and_reopen_returns_completed_reply(self):
        stored_messages = []
        release_generation = threading.Event()
        generation_finished = threading.Event()
        session = {"user_id": 42}

        def save_message(room_id, message, sender, attached_file_names=None, parent_id=None, *args, **kwargs):
            stored_messages.append((room_id, message, sender))
            if sender == "assistant":
                generation_finished.set()
            return len(stored_messages)

        def active_leaf_id(room_id):
            room_messages = [m for m in stored_messages if m[0] == room_id]
            return len(room_messages) or None

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
            patch("blueprints.chat.messages.get_active_leaf_id", side_effect=active_leaf_id),
            patch("blueprints.chat.messages.get_chat_room_messages", side_effect=get_messages),
            patch("blueprints.chat.messages._fetch_chat_history", side_effect=fetch_history),
            patch("blueprints.chat.messages.get_user_by_id", return_value={}),
            patch("blueprints.chat.messages.get_room_summary", return_value={}),
            patch("blueprints.chat.messages.list_room_memory_facts", return_value=[]),
            patch("blueprints.chat.messages.rebuild_room_summary"),
            patch("services.chat_use_case.generate_chat_room_title", return_value=None),
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
            # Persistence completes immediately before the terminal event marks the
            # background job done, so allow that final callback to cross the thread boundary.
            for _ in range(100):
                if not has_active_generation(generation_key):
                    break
                threading.Event().wait(0.01)
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

    # 日本語: 再生成(regenerate)時、過去にアップロードされた添付ファイル内容が再度LLMに入力されることを検証します。
    # English: Verify that regeneration reinjects previously saved attachment contents into the LLM context.
    def test_regenerate_reinjects_saved_attachment_contents_for_llm(self):
        captured_messages = {}
        request = build_request(
            method="POST",
            path="/api/chat_regenerate",
            json_body={
                "chat_room_id": "room-1",
                "model": "claude-haiku-4-5-20251001",
                "use_personal_knowledge": True,
                "use_shared_prompts": True,
            },
            session={"user_id": 42},
        )

        def get_llm_response(messages, model):
            captured_messages["messages"] = messages
            return "new answer"

        with (
            patch("blueprints.chat.messages.cleanup_ephemeral_chats"),
            patch("blueprints.chat.messages.validate_model_name"),
            patch("blueprints.chat.messages.validate_room_owner", new=AsyncMock(return_value=None)),
            patch(
                "blueprints.chat.messages.get_active_path",
                new=AsyncMock(return_value=[
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
                ]),
            ),
            patch("blueprints.chat.messages.get_user_by_id", new=AsyncMock(return_value={})),
            patch("blueprints.chat.messages.get_room_summary", new=AsyncMock(return_value={})),
            patch("blueprints.chat.messages.list_room_memory_facts", new=AsyncMock(return_value=[])),
            patch(
                "blueprints.chat.messages.get_room_web_search_contexts",
                new=AsyncMock(return_value=[]),
            ),
            patch("blueprints.chat.messages.consume_llm_daily_quota", return_value=(True, 1, 300)),
            patch("blueprints.chat.messages.is_streaming_model", return_value=False),
            patch(
                "blueprints.chat.messages.search_personal_knowledge_for_tool",
                new=AsyncMock(return_value={
                    "status": "ok",
                    "memo_count": 1,
                    "context_fact_count": 0,
                    "memos": [{"title": "要約方針", "content": "結論を先に書く"}],
                    "context_facts": [],
                }),
            ) as personal_search,
            patch(
                "blueprints.chat.messages.search_shared_prompts_for_tool",
                new=AsyncMock(return_value={
                    "status": "ok",
                    "prompt_count": 1,
                    "prompts": [{"title": "要約テンプレ"}],
                }),
            ) as shared_search,
            patch("blueprints.chat.messages.get_llm_response", side_effect=get_llm_response),
            patch("blueprints.chat.messages.save_message_to_db", new=AsyncMock(return_value=12)),
        ):
            response = asyncio.run(chat_regenerate(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["response"].endswith("new answer"))
        self.assertIn("メモとマイコンテキストを検索", payload["response"])
        self.assertIn("共有プロンプトを検索", payload["response"])
        contents = [message["content"] for message in captured_messages["messages"]]
        self.assertTrue(any("PDF BODY" in content for content in contents))
        self.assertFalse(any("old answer" in content for content in contents))
        self.assertTrue(any("要約方針" in content and "要約テンプレ" in content for content in contents))
        personal_search.assert_awaited_once_with(42, "要約して")
        shared_search.assert_awaited_once_with("要約して")

    # 日本語: メッセージを編集して再生成する際、元の添付ファイル内容が正しく引き継がれることを検証します。
    # English: Verify that editing a message and regenerating it preserves the original attachment contents.
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
                "model": "claude-haiku-4-5-20251001",
                "use_personal_knowledge": True,
            },
            session={"user_id": 42},
        )

        def save_message(*args, **kwargs):
            saved_messages.append((args, kwargs))
            return 20 + len(saved_messages)

        def get_llm_response(messages, model):
            captured_messages["messages"] = messages
            return "edited answer"

        with (
            patch("blueprints.chat.messages.cleanup_ephemeral_chats"),
            patch("blueprints.chat.messages.validate_model_name"),
            patch("blueprints.chat.messages.validate_room_owner", new=AsyncMock(return_value=None)),
            patch(
                "blueprints.chat.messages.get_active_path",
                new=AsyncMock(return_value=[
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
                ]),
            ),
            patch("blueprints.chat.messages.get_user_by_id", new=AsyncMock(return_value={})),
            patch("blueprints.chat.messages.get_room_summary", new=AsyncMock(return_value={})),
            patch("blueprints.chat.messages.list_room_memory_facts", new=AsyncMock(return_value=[])),
            patch(
                "blueprints.chat.messages.get_room_web_search_contexts",
                new=AsyncMock(return_value=[]),
            ),
            patch("blueprints.chat.messages.consume_llm_daily_quota", return_value=(True, 1, 300)),
            patch("blueprints.chat.messages.is_streaming_model", return_value=False),
            patch(
                "blueprints.chat.messages.search_personal_knowledge_for_tool",
                new=AsyncMock(return_value={
                    "status": "ok",
                    "memo_count": 1,
                    "context_fact_count": 0,
                    "memos": [{"title": "文章方針", "content": "短くまとめる"}],
                    "context_facts": [],
                }),
            ) as personal_search,
            patch("blueprints.chat.messages.get_llm_response", side_effect=get_llm_response),
            patch(
                "blueprints.chat.messages.save_message_to_db",
                new=AsyncMock(side_effect=save_message),
            ),
        ):
            response = asyncio.run(chat_edit_and_regenerate(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["response"].endswith("edited answer"))
        self.assertIn("メモとマイコンテキストを検索", payload["response"])
        contents = [message["content"] for message in captured_messages["messages"]]
        self.assertTrue(any("PDF BODY" in content for content in contents))
        self.assertTrue(any("文章方針" in content for content in contents))
        personal_search.assert_awaited_once_with(42, "この資料を短く要約して")
        user_save_args, user_save_kwargs = saved_messages[0]
        self.assertEqual(user_save_args[3], ["sample.pdf"])
        self.assertIn("attached_file_contents", user_save_kwargs)

    # 日本語: 履歴取得APIにおいて、指定されたlimitおよびbefore_idパラメータが正しく内部処理に伝達されることを検証します。
    # English: Verify that limit and before_id parameters are correctly forwarded in get_chat_history API.
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

    # 日本語: 履歴取得APIでlimitが指定されない場合、デフォルトのページサイズ制限が適用されることを検証します。
    # English: Verify that get_chat_history API falls back to the default page size limit when no limit is provided.
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

    # 日本語: セッションに登録されていないゲストルームの履歴取得要求に対して、404エラーを返すことを検証します。
    # English: Verify that requesting history for a guest room not registered in the session returns a 404 error.
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

    # 日本語: セッションに登録されていないゲストルームの生成ストリーム取得要求に対して、404エラーを返すことを検証します。
    # English: Verify that requesting generation stream for an unregistered guest room returns a 404 error.
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


    # 日本語: 生成が完了した直後のステータス要求において、再生可能なジョブ情報(has_replayable_job)が含まれることを検証します。
    # English: Verify that generation status includes has_replayable_job when a completed job is present.
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
            # 日本語: ジョブを完了させるために、すべてのイベントを消費します。
            # English: consume all events so the job finishes
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

    # 日本語: 生成完了後にストリーム接続した際、過去に完了したジョブの結果がストリーミングで再生されることを検証します。
    # English: Verify that connecting to the stream after completion replays the completed job events.
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
            # 日本語: ジョブを完了させるために、すべてのイベントを消費します。
            # English: consume all events so the job finishes
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

        # 日本語: ストリームレスポンスを消費して結合する非同期ヘルパー
        # English: Async helper to consume and concatenate stream response chunks
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

    # 日本語: 対応するジョブが存在しない状態でストリームに接続しようとした場合に、404エラーとなることを検証します。
    # English: Verify that attempting to stream when no corresponding job exists returns a 404 error.
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

    # 日本語: Last-Event-IDヘッダーが指定された場合、すでにクライアントが受信済みのイベントをスキップして残りを送信することを検証します。
    # English: Verify that the stream skips already received events by checking the Last-Event-ID header.
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
            headers=[(b"last-event-id", b"3")],
        )
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value=(None, None)):
                stream_response = asyncio.run(chat_generation_stream(stream_request))

        # 日本語: ストリームレスポンスを消費して結合する非同期ヘルパー
        # English: Async helper to consume and concatenate stream response chunks
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

    # 日本語: ローカルジョブがない場合でも、Redis上の分散イベントログからイベントが正しく再生されることを検証します。
    # English: Verify that distributed events are replayed from the Redis event stream even without a local job.
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

        # 日本語: ストリームレスポンスを消費して結合する非同期ヘルパー
        # English: Async helper to consume and concatenate stream response chunks
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

    # 日本語: 分散環境下で実行中のジョブが停止(stalled)した場合、一定時間経過後にタイムアウトエラーとなることを検証します。
    # English: Verify that a stalled distributed job times out after a certain period of inactivity.
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

        # 日本語: ストリームレスポンスを消費して結合する非同期ヘルパー
        # English: Async helper to consume and concatenate stream response chunks
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
