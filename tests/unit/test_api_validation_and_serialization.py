import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from blueprints.auth import api_send_login_code
from blueprints.chat.messages import chat
from blueprints.chat.tasks import update_tasks_order
from blueprints.prompt_share.prompt_manage_api import get_my_prompts
from services.web_search import WebSearchAugmentation, WebSearchResult, WebSearchSource
from tests.helpers.request_helpers import build_request


# APIテスト用のHTTPリクエストを構築します。
# Build a mock HTTP request for testing API endpoints.
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


# APIの入力検証（バリデーション：不正なJSON形式のハンドリング等）と出力のシリアライズ処理（日付のフォーマット、Web検索ソースのHTML整形等）をテストするクラス。
# Test class to check API input validation (e.g. malformed JSON) and response serialization (e.g. datetimes, web search sources layout).
class ApiValidationAndSerializationTestCase(unittest.TestCase):
    # タスクの並び順更新APIが、不正なJSON形式のリクエストに対して400エラーで拒否することを検証します。
    # Verify that the update tasks order API rejects malformed JSON payloads with a 400 error.
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

    # ログインコード送信APIが、不正なJSON形式のリクエストに対してステータス"fail"の400エラーで拒否することを検証します。
    # Verify that the send login code API rejects malformed JSON payloads with a 400 error and a "fail" status.
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

    # 存在しない一時チャットルーム（ephemeral room）への投稿が、404エラー（見つからない）として返却されることを検証します。
    # Verify that posting to a non-existent ephemeral room returns a 404 error response.
    def test_chat_missing_ephemeral_room_returns_404_response(self):
        request = make_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "missing-room"},
            session={},
        )

        # ephemeral roomの存在有無判定をモック
        # Mock room existence checks and run the chat API handler
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

    # 無効または利用不可能なLLMモデル名が指定された場合に、400エラーで拒否されることを検証します。
    # Verify that requesting an invalid or unavailable LLM model returns a 400 error.
    def test_chat_returns_400_when_invalid_model_is_requested(self):
        request = make_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "room-1", "model": "invalid-model"},
            session={},
        )

        # 各種処理をモックして無効なモデル名指定時の挙動を検証
        # Mock various handlers and components to check response when invalid model is specified
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

    # チャットの正常応答において、Web検索によって補強された場合に、検索ソースと詳細情報（参照URL等）がレスポンスに含まれていることを検証します。
    # Verify that successful chat responses augmented with web search results include the search sources metadata in the payload.
    def test_chat_json_response_path_includes_web_search_sources(self):
        request = make_request(
            method="POST",
            path="/api/chat",
            json_body={
                "message": "今日のOpenAIの最新ニュースを教えて",
                "chat_room_id": "room-1",
                "model": "openai/gpt-oss-120b",
            },
            session={},
        )

        search_result = WebSearchResult(
            query="OpenAI 最新ニュース 今日",
            searched_at="2026-05-06T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/openai-news",
                    title="OpenAI News",
                    hostname="example.com",
                    age="2026-05-06",
                    snippets=(),
                ),
            ),
        )

        # Web検索結果の拡張及びLLM呼び出し結果をモック
        # Mock search augmentation result and the subsequent LLM response
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch(
                        "blueprints.chat.messages.ephemeral_store.get_messages",
                        return_value=[{"role": "user", "content": "今日のOpenAIの最新ニュースを教えて"}],
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
                                        "services.chat_use_case.maybe_augment_messages_with_web_search",
                                        return_value=WebSearchAugmentation(
                                            messages=[{"role": "user", "content": "今日のOpenAIの最新ニュースを教えて"}],
                                            result=search_result,
                                        ),
                                    ) as mock_augment:
                                        with patch(
                                            "blueprints.chat.messages.get_llm_response",
                                            return_value="最新ニュースです。",
                                        ) as mock_llm:
                                            response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("最新ニュースです。", payload["response"])
        self.assertTrue(payload["response"].startswith('<details class="web-search-sources web-search-sources--trace">'))
        self.assertIn('<summary class="web-search-sources__summary">', payload["response"])
        self.assertIn('<span class="web-search-sources__label">回答までのステップ</span>', payload["response"])
        self.assertIn('<span class="web-search-sources__count">4ステップ / 1件</span>', payload["response"])
        self.assertIn('<div class="web-search-sources__section-title">参照したWebサイト</div>', payload["response"])
        self.assertIn("https://example.com/openai-news", payload["response"])
        mock_augment.assert_called_once()
        self.assertEqual(mock_llm.call_args.args[1], "openai/gpt-oss-120b")

    # プロンプト管理APIにおける日付オブジェクトが、ISO-8601形式（YYYY-MM-DDTHH:MM:SS）で一貫してシリアライズされることを検証します。
    # Verify that datetime objects in prompt management API payloads are consistently serialized to ISO-8601 format.
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

        # プロンプト一覧取得処理をモック
        # Mock fetching user prompts and verify serialized datetime format
        with patch(
            "blueprints.prompt_share.prompt_manage_api._fetch_my_prompts",
            return_value=sample_prompts,
        ):
            response = asyncio.run(get_my_prompts(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["prompts"][0]["created_at"], "2024-01-02T03:04:05")


if __name__ == "__main__":
    unittest.main()
