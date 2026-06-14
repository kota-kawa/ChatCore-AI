import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.rooms import share_chat_room, shared_chat_room
from tests.helpers.request_helpers import build_request


# 日本語: make share request の生成処理を担当します。
# English: Handle creating for make share request.
def make_share_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/share_chat_room",
        json_body=json_body,
        session=session,
    )


# 日本語: make shared read request の生成処理を担当します。
# English: Handle creating for make shared read request.
def make_shared_read_request(token: str):
    return build_request(
        method="GET",
        path="/api/shared_chat_room",
        query_string=f"token={token}".encode("utf-8"),
        session={},
    )


# 日本語: Chat Room Sharingの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Chat Room Sharing.
class ChatRoomSharingTestCase(unittest.TestCase):
    # 日本語: shareチャットroom要求するログインことを検証します。
    # English: Verify that share chat room requires login.
    def test_share_chat_room_requires_login(self):
        request = make_share_request({"room_id": "room-1"}, session={})

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            response = asyncio.run(share_chat_room(request))

        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "ログインが必要です")

    # 日本語: 〜しないownerのとき、shareチャットroom返却する403ことを検証します。
    # English: Verify that share chat room returns 403 when not owner.
    def test_share_chat_room_returns_403_when_not_owner(self):
        request = make_share_request({"room_id": "room-1"}, session={"user_id": 10})

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.validate_room_owner",
                return_value=({"error": "他ユーザーのチャットルームは共有できません"}, 403),
            ):
                response = asyncio.run(share_chat_room(request))

        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "他ユーザーのチャットルームは共有できません")

    # 日本語: 成功するにおける、shareチャットroom返却するshareURLことを検証します。
    # English: Verify that share chat room returns share url on success.
    def test_share_chat_room_returns_share_url_on_success(self):
        request = make_share_request({"room_id": "room-42"}, session={"user_id": 3})

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms.validate_room_owner", return_value=(None, None)):
                with patch(
                    "blueprints.chat.rooms.create_or_get_shared_chat_token",
                    return_value=("abc123token", None),
                ):
                    with patch(
                        "blueprints.chat.rooms.frontend_url",
                        return_value="https://chatcore-ai.com/shared/abc123token",
                    ):
                        response = asyncio.run(share_chat_room(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["share_token"], "abc123token")
        self.assertEqual(payload["share_url"], "https://chatcore-ai.com/shared/abc123token")

    # 日本語: sharedチャットroom要求するトークンことを検証します。
    # English: Verify that shared chat room requires token.
    def test_shared_chat_room_requires_token(self):
        request = build_request(
            method="GET",
            path="/api/shared_chat_room",
            query_string=b"",
            session={},
        )
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            response = asyncio.run(shared_chat_room(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "token is required")

    # 日本語: sharedチャットroom返却するペイロードことを検証します。
    # English: Verify that shared chat room returns payload.
    def test_shared_chat_room_returns_payload(self):
        request = make_shared_read_request("share-token-1")
        expected = (
            {
                "room": {
                    "id": "room-1",
                    "title": "共有テスト",
                    "created_at": "2026-03-21T12:00:00",
                },
                "messages": [
                    {
                        "message": "こんにちは",
                        "sender": "user",
                        "timestamp": "2026-03-21T12:00:01",
                    }
                ],
            },
            200,
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.get_shared_chat_room_payload",
                return_value=expected,
            ):
                response = asyncio.run(shared_chat_room(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["room"]["id"], "room-1")
        self.assertEqual(payload["messages"][0]["message"], "こんにちは")

    # 日本語: sharedチャットroom返却する〜しないfoundことを検証します。
    # English: Verify that shared chat room returns not found.
    def test_shared_chat_room_returns_not_found(self):
        request = make_shared_read_request("missing")
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.get_shared_chat_room_payload",
                return_value=({"error": "共有リンクが見つかりません"}, 404),
            ):
                response = asyncio.run(shared_chat_room(request))

        self.assertEqual(response.status_code, 404)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "共有リンクが見つかりません")


if __name__ == "__main__":
    unittest.main()
