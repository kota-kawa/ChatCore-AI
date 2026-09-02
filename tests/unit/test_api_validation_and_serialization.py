import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from blueprints.auth import api_send_login_code
from blueprints.chat.messages import chat
from blueprints.chat.tasks import update_tasks_order
from blueprints.prompt_share.prompt_manage_api import get_my_prompts
import services.chat_use_case as chat_use_case
from services.research_state import is_reference_context_message
from tests.helpers.request_helpers import build_request


# 日本語: APIテスト用のHTTPリクエストを構築します。
# English: Build a mock HTTP request for testing API endpoints.
def make_request(
    *,
    method: str,
    path: str,
    session=None,
    json_body=None,
    raw_body: bytes | None = None,
):
    return build_request(
        method=method,
        path=path,
        session=session,
        json_body=json_body,
        raw_body=raw_body,
    )


# 日本語: APIの入力検証（バリデーション：不正なJSON形式のハンドリング等）と出力のシリアライズ処理（日付のフォーマット、Web検索ソースのHTML整形等）をテストするクラス。
# English: Test class to check API input validation (e.g. malformed JSON) and response serialization (e.g. datetimes, web search sources layout).
class ApiValidationAndSerializationTestCase(unittest.TestCase):
    # 日本語: タスクの並び順更新APIが、不正なJSON形式のリクエストに対して400エラーで拒否することを検証します。
    # English: Verify that the update tasks order API rejects malformed JSON payloads with a 400 error.
    def test_chat_update_tasks_order_rejects_malformed_json(self):
        request = make_request(
            method="POST",
            path="/api/update_tasks_order",
            session={"user_id": 1},
            raw_body=b"{",
        )

        response = asyncio.run(update_tasks_order(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "JSON形式が不正です。")

    # 日本語: ログインコード送信APIが、不正なJSON形式のリクエストに対してステータス"fail"の400エラーで拒否することを検証します。
    # English: Verify that the send login code API rejects malformed JSON payloads with a 400 error and a "fail" status.
    def test_auth_send_login_code_rejects_malformed_json_with_fail_status(self):
        request = make_request(
            method="POST",
            path="/api/send_login_code",
            raw_body=b"{",
        )

        response = asyncio.run(api_send_login_code(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "JSON形式が不正です。")

    # 日本語: 存在しない一時チャットルーム（ephemeral room）への投稿が、404エラー（見つからない）として返却されることを検証します。
    # English: Verify that posting to a non-existent ephemeral room returns a 404 error response.
    def test_chat_missing_ephemeral_room_returns_404_response(self):
        request = make_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "missing-room"},
            session={},
        )

        # 日本語: ephemeral roomの存在有無判定をモック
        # English: Mock room existence checks and run the chat API handler
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=False):
                    response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 404)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "該当ルームが見つかりません")

    # 日本語: 無効または利用不可能なLLMモデル名が指定された場合に、400エラーで拒否されることを検証します。
    # English: Verify that requesting an invalid or unavailable LLM model returns a 400 error.
    def test_chat_returns_400_when_invalid_model_is_requested(self):
        request = make_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "room-1", "model": "invalid-model"},
            session={},
        )

        # 日本語: 各種処理をモックして無効なモデル名指定時の挙動を検証
        # English: Mock various handlers and components to check response when invalid model is specified
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch("blueprints.chat.messages.ephemeral_store.get_messages", return_value=[]):
                        with patch("blueprints.chat.messages.ephemeral_store.append_message"):
                            with patch("blueprints.chat.messages.consume_llm_daily_quota") as mock_quota:
                                with patch("blueprints.chat.messages.get_llm_response") as mock_llm:
                                    response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("無効なモデル", payload["error"])
        mock_quota.assert_not_called()
        mock_llm.assert_not_called()

    # 日本語: 非ストリーミング互換経路でも事前検索Plannerを起動せず、モデル自身の回答を
    # そのまま返すことを検証します。検索判断は単一の判断ループだけが行います。
    # English: Verify the non-streaming compatibility path runs no separate search planner and
    # returns the model's own answer; only the single decision loop decides to search.
    def test_chat_json_response_path_runs_without_a_search_planner(self):
        conversation = [{"role": "user", "content": "今日のOpenAI of the day を教えて"}]
        request = make_request(
            method="POST",
            path="/api/chat",
            json_body={
                "message": "今日のOpenAI of the day を教えて",
                "chat_room_id": "room-1",
                "model": "openai/gpt-oss-120b",
            },
            session={},
        )

        # 事前検索Plannerは実装ごと存在しない。パッチ対象として復活していないことも確認する。
        # The search planner no longer exists; assert it has not come back as a patch target.
        self.assertFalse(
            hasattr(chat_use_case, "maybe_augment_messages_with_web_search")
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch(
                        "blueprints.chat.messages.ephemeral_store.get_messages",
                        return_value=list(conversation),
                    ):
                        with patch("blueprints.chat.messages.ephemeral_store.append_message"):
                            with patch(
                                "blueprints.chat.messages.consume_llm_daily_quota",
                                return_value=(True, 1, 300),
                            ):
                                with patch(
                                    "blueprints.chat.messages.is_streaming_model",
                                    return_value=False,
                                ):
                                    with patch(
                                        "blueprints.chat.messages.get_llm_response",
                                        return_value="最新ニュースです。",
                                    ) as mock_llm:
                                        response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "最新ニュースです。")
        # 検索していないので、回答トレースも検索由来のパーツも作らない。
        # Nothing was searched, so neither a trace block nor search-derived parts are built.
        self.assertNotIn("web-search-sources", payload["response"])
        self.assertIsNone(payload.get("parts"))
        # 会話は標準のsystem指示だけを伴い、検索由来の参照ブロックは足されない。
        # The conversation carries only the standing system instructions: no injected
        # search-context block is added ahead of the answer.
        sent_messages = mock_llm.call_args.args[0]
        self.assertEqual(sent_messages[-1], conversation[0])
        self.assertFalse(
            any(is_reference_context_message(message) for message in sent_messages)
        )
        self.assertEqual(mock_llm.call_args.args[1], "openai/gpt-oss-120b")

    # 日本語: プロンプト管理APIにおける日付オブジェクトが、ISO-8601形式（YYYY-MM-DDTHH:MM:SS）で一貫してシリアライズされることを検証します。
    # English: Verify that datetime objects in prompt management API payloads are consistently serialized to ISO-8601 format.
    def test_prompt_manage_serializes_datetime_consistently(self):
        request = make_request(
            method="GET",
            path="/prompt_manage/api/my_prompts",
            session={"user_id": 99},
        )
        sample_prompts = [
            {
                "id": 1,
                "title": "title",
                "category": "cat",
                "content": "content",
                "input_examples": "",
                "output_examples": "",
                "created_at": datetime(2024, 1, 2, 3, 4, 5),
            }
        ]

        # 日本語: プロンプト一覧取得処理をモック
        # English: Mock fetching user prompts and verify serialized datetime format
        with patch(
            "blueprints.prompt_share.prompt_manage_api._fetch_my_prompts",
            new=AsyncMock(return_value=sample_prompts),
        ):
            response = asyncio.run(get_my_prompts(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["prompts"][0]["created_at"], "2024-01-02T03:04:05")


if __name__ == "__main__":
    unittest.main()
