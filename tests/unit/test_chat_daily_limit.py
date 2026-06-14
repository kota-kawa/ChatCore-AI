import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.messages import chat
from tests.helpers.request_helpers import build_request


# 日本語: チャットAPIテスト用のPOSTリクエストを構築するヘルパー関数。
# English: Helper function to build a POST request for chat API testing.
def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/chat",
        json_body=json_body,
        session=session,
    )


# 日本語: チャット1日あたり利用制限（ゲスト制限・グローバル制限）をテストするクラス。
# English: Test class for chat daily usage limits (guest limit and global limit).
class ChatDailyLimitTestCase(unittest.TestCase):
    # 日本語: セッションにゲスト制限超過の状態が設定されている場合に、チャットAPIが429を返すことを検証します。
    # English: Verify that the chat API returns 429 when the session indicates the guest daily limit is exceeded.
    def test_chat_returns_429_when_guest_daily_limit_exceeded(self):
        # 日本語: 制限超過を示すカウントと日付をセッションにセット
        # English: Set a count and date in the session indicating limit exhaustion
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "gemini-2.5-flash"},
            session={"free_chats_count": "999999", "free_chats_date": "2099-01-01"},
        )

        # 日本語: ゲスト制限消費をFalseでモックして制限超過状態を再現
        # English: Mock guest limit consumption returning False to simulate limit exhaustion
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(False, "1日10回までです"),
            ) as mock_guest_limit:
                with patch("blueprints.chat.messages.ephemeral_store.room_exists") as mock_room_exists:
                    with patch("blueprints.chat.messages.consume_llm_daily_quota") as mock_llm_quota:
                        response = asyncio.run(chat(request))

        # 日本語: 429ステータス、Retry-Afterヘッダー、ゲスト制限エラーメッセージを確認
        # English: Confirm 429 status, Retry-After header, and guest limit error message
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.headers.get("Retry-After"))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "1日10回までです")
        mock_guest_limit.assert_called_once()
        # 日本語: ゲスト制限で弾かれた場合、以降の処理は呼ばれていないこと
        # English: Confirm subsequent calls are skipped when blocked by guest limit
        mock_room_exists.assert_not_called()
        mock_llm_quota.assert_not_called()

    # 日本語: ゲスト制限超過時にカスタムエラーメッセージがそのままレスポンスに含まれることを検証します。
    # English: Verify that the custom error message from the guest limit is included in the 429 response.
    def test_chat_returns_429_when_guest_daily_limit_exceeded_with_custom_message(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "gemini-2.5-flash"},
            session={},
        )

        # 日本語: カスタムエラーメッセージを返す制限超過状態をモック
        # English: Mock limit exhaustion with a custom error message
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(False, "1日3回までです"),
            ):
                response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.headers.get("Retry-After"))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "1日3回までです")

    # 日本語: グローバルなLLM1日利用制限を超過した場合に、チャットAPIが429を返すことを検証します。
    # English: Verify that the chat API returns 429 when the global LLM daily quota is exceeded.
    def test_chat_returns_429_when_global_daily_limit_exceeded(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "gemini-2.5-flash"},
            session={},
        )

        # 日本語: ゲスト制限は通過させつつ、グローバルLLMクォータを超過させる状態をモック
        # English: Mock scenario where guest limit passes but global LLM quota is exhausted
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch("blueprints.chat.messages.ephemeral_store.get_messages", return_value=[]):
                        with patch("blueprints.chat.messages.ephemeral_store.append_message"):
                            with patch(
                                "blueprints.chat.messages.consume_llm_daily_quota",
                                return_value=(False, 0, 300),
                            ):
                                with patch("blueprints.chat.messages.get_llm_response") as mock_llm:
                                    response = asyncio.run(chat(request))

        # 日本語: グローバル制限超過の場合、LLMは呼ばれず429が返ることを確認
        # English: Confirm LLM is not called and 429 is returned when global limit is exceeded
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.headers.get("Retry-After"))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("上限", payload["error"])
        mock_llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
