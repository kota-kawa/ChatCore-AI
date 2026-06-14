import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.rooms import new_chat_room
from tests.helpers.request_helpers import build_request


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/new_chat_room",
        json_body=json_body,
        session=session,
    )


# 日本語: ChatRoomsGuestDailyLimitTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatRoomsGuestDailyLimitTestCase.
class ChatRoomsGuestDailyLimitTestCase(unittest.TestCase):
    # 日本語: test new chat room returns 429 when guest daily limit exceeded のテスト検証を担当します。
    # English: Handle verifying test behavior for test new chat room returns 429 when guest daily limit exceeded.
    def test_new_chat_room_returns_429_when_guest_daily_limit_exceeded(self):
        request = make_request(
            {"id": "room-guest-limit", "title": "Guest room"},
            session={"free_chats_count": "100", "free_chats_date": "2099-12-31"},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.consume_guest_chat_daily_limit",
                return_value=(False, "1日10回までです"),
            ) as mock_guest_limit:
                with patch("blueprints.chat.rooms.ephemeral_store.create_room") as mock_create_room:
                    response = asyncio.run(new_chat_room(request))

        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.headers.get("Retry-After"))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "1日10回までです")
        mock_guest_limit.assert_called_once()
        mock_create_room.assert_not_called()

    # 日本語: test new chat room creates ephemeral room when guest limit allows のテスト検証を担当します。
    # English: Handle verifying test behavior for test new chat room creates ephemeral room when guest limit allows.
    def test_new_chat_room_creates_ephemeral_room_when_guest_limit_allows(self):
        request = make_request({"id": "room-guest-ok", "title": "Guest room"}, session={})

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.rooms.get_session_id", return_value="sid-1"):
                    with patch("blueprints.chat.rooms.ephemeral_store.create_room") as mock_create_room:
                        response = asyncio.run(new_chat_room(request))

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["id"], "room-guest-ok")
        mock_create_room.assert_called_once_with("sid-1", "room-guest-ok", "Guest room")


if __name__ == "__main__":
    unittest.main()
