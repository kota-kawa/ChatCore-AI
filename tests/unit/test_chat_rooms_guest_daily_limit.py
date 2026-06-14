import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.rooms import new_chat_room
from tests.helpers.request_helpers import build_request


# 日本語: 新規チャットルーム作成のテスト用リクエストを構築するヘルパー関数
# English: Helper function to build a test request for creating a new chat room
def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/new_chat_room",
        json_body=json_body,
        session=session,
    )


# 日本語: ゲストユーザーの1日あたりチャットルーム作成制限に関するユニットテスト
# English: Unit tests for guest user daily limit on creating chat rooms
class ChatRoomsGuestDailyLimitTestCase(unittest.TestCase):
    # 日本語: ゲストユーザーの1日あたりの作成制限を超過した場合に429エラー(Too Many Requests)を返すことを検証します。
    # English: Verify that creating a new chat room returns 429 when the guest daily limit is exceeded.
    def test_new_chat_room_returns_429_when_guest_daily_limit_exceeded(self):
        # 日本語: 既に作成上限に達した状態を示すセッション情報を含めたリクエストを作成
        # English: Create a request with session info indicating that the daily limit is already reached
        request = make_request(
            {"id": "room-guest-limit", "title": "Guest room"},
            session={"free_chats_count": "100", "free_chats_date": "2099-12-31"},
        )

        # 日本語: 一時チャットクリーンアップ、ゲスト制限消費、およびルーム作成処理をモック化
        # English: Mock ephemeral chat cleanup, guest limit consumption, and room creation
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.consume_guest_chat_daily_limit",
                return_value=(False, "1日10回までです"),
            ) as mock_guest_limit:
                with patch("blueprints.chat.rooms.ephemeral_store.create_room") as mock_create_room:
                    response = asyncio.run(new_chat_room(request))

        # 日本語: レスポンスが429であること、Retry-Afterヘッダーが存在すること、およびエラーメッセージが正しいことを検証
        # English: Assert that status is 429, Retry-After header is set, and error message matches
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.headers.get("Retry-After"))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "1日10回までです")
        mock_guest_limit.assert_called_once()
        mock_create_room.assert_not_called()

    # 日本語: ゲストユーザーの1日あたりの作成制限に達していない場合、一時的なチャットルームが正常に作成できることを検証します。
    # English: Verify that a new ephemeral chat room is successfully created when the guest daily limit is not exceeded.
    def test_new_chat_room_creates_ephemeral_room_when_guest_limit_allows(self):
        # 日本語: 空のセッション情報で新規ルーム作成リクエストを作成
        # English: Create a new room request with an empty session
        request = make_request({"id": "room-guest-ok", "title": "Guest room"}, session={})

        # 日本語: 一時チャットクリーンアップ、ゲスト制限、セッションID取得、およびルーム作成処理をモック化
        # English: Mock ephemeral chat cleanup, guest limit validation, session ID retrieval, and room creation
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.rooms.get_session_id", return_value="sid-1"):
                    with patch("blueprints.chat.rooms.ephemeral_store.create_room") as mock_create_room:
                        response = asyncio.run(new_chat_room(request))

        # 日本語: 正常作成(201 Created)され、レスポンスに正しいIDが含まれ、作成関数が期待通り呼び出されたことを検証
        # English: Assert that creation returns 201, matches room ID, and calls create_room with expected arguments
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["id"], "room-guest-ok")
        mock_create_room.assert_called_once_with("sid-1", "room-guest-ok", "Guest room")


if __name__ == "__main__":
    unittest.main()
