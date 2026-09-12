import asyncio
import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from blueprints.chat.rooms import revoke_chat_room_share, share_chat_room, shared_chat_room
from services.api_errors import ResourceNotFoundError
from services.error_messages import ERROR_SHARED_LINK_NOT_FOUND
from tests.helpers.request_helpers import build_request


# 日本語: チャットルーム共有リクエストを作成するヘルパー関数
# English: Helper function to create a chat room sharing request
def make_share_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/share_chat_room",
        json_body=json_body,
        session=session,
    )


# 日本語: 共有リンクの失効リクエストを作成するヘルパー関数
# English: Helper function to create a chat room share revocation request
def make_revoke_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/revoke_chat_room_share",
        json_body=json_body,
        session=session,
    )


# 日本語: 共有状態のシリアライズ済みペイロードを作成するヘルパー関数
# English: Helper that builds a serialized share-state payload
def share_state(*, share_token="abc123token", expires_at=None, revoked_at=None, is_reused=False):
    return {
        "share_token": share_token,
        "expires_at": expires_at,
        "revoked_at": revoked_at,
        "is_expired": False,
        "is_revoked": revoked_at is not None,
        "is_active": revoked_at is None,
        "is_reused": is_reused,
    }


# 日本語: 共有されたチャットルームの読み取りリクエストを作成するヘルパー関数
# English: Helper function to create a request to read a shared chat room
def make_shared_read_request(token: str):
    return build_request(
        method="GET",
        path="/api/shared_chat_room",
        query_string=f"token={token}".encode(),
        session={},
    )


# 日本語: チャットルーム共有機能のユニットテスト
# English: Unit tests for chat room sharing functionality
class ChatRoomSharingTestCase(unittest.TestCase):
    # 日本語: 未ログインのユーザーがチャットルームを共有しようとした場合に403エラーとなることを検証します。
    # English: Verify that sharing a chat room returns 403 when the user is not logged in.
    def test_share_chat_room_requires_login(self):
        # 日本語: 未ログイン状態（sessionが空）で共有リクエストを作成
        # English: Create a share request without being logged in (empty session)
        request = make_share_request({"room_id": "room-1"}, session={})

        # 日本語: 一時チャットクリーンアップ処理をモック化してリクエストを実行
        # English: Mock the cleanup process of ephemeral chats and run the request
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            response = asyncio.run(share_chat_room(request))

        # 日本語: レスポンスが403であり、ログインが必要な旨のエラーメッセージが含まれることを確認
        # English: Assert that response is 403 and contains login-required error message
        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "ログインが必要です")

    # 日本語: 所有者ではないユーザーがチャットルームを共有しようとした場合に403エラーとなることを検証します。
    # English: Verify that sharing a chat room returns 403 when the requester is not the room owner.
    def test_share_chat_room_returns_403_when_not_owner(self):
        # 日本語: ユーザーID: 10として共有リクエストを作成
        # English: Create a share request with user ID 10
        request = make_share_request({"room_id": "room-1"}, session={"user_id": 10})

        # 日本語: 所有者検証をモック化し、他人のルームであるためエラーを返すように設定
        # English: Mock room owner validation to return an error indicating it belongs to another user
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.validate_room_owner",
                return_value=({"error": "他ユーザーのチャットルームは共有できません"}, 403),
            ):
                response = asyncio.run(share_chat_room(request))

        # 日本語: レスポンスが403であり、エラーメッセージが適切であることを確認
        # English: Assert that response is 403 and the error message is correct
        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "他ユーザーのチャットルームは共有できません")

    # 日本語: チャットルームの所有者が正常に共有できた場合に、共有用URLとトークンが返されることを検証します。
    # English: Verify that successful sharing by the owner returns the share URL and token.
    def test_share_chat_room_returns_share_url_on_success(self):
        # 日本語: 所有者（ユーザーID: 3）として共有リクエストを作成
        # English: Create a share request as the owner (user ID 3)
        request = make_share_request({"room_id": "room-42"}, session={"user_id": 3})

        # 日本語: 所有者検証、トークン生成、およびフロントエンドのベースURLをモック化
        # English: Mock the owner validation, token generation, and the frontend base URL
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms.validate_room_owner", return_value=(None, None)):
                with patch(
                    "blueprints.chat.rooms.create_or_get_shared_chat_token",
                    return_value=share_state(),
                ):
                    with patch(
                        "services.web_constants.FRONTEND_URL",
                        "https://chatcore-ai.com",
                    ):
                        response = asyncio.run(share_chat_room(request))

        # 日本語: 正常終了し、生成されたトークンとURLがレスポンスに含まれていることを確認
        # English: Assert success status and check that the token and URL are in the response
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["share_token"], "abc123token")
        self.assertEqual(payload["share_url"], "https://chatcore-ai.com/shared/abc123token")
        self.assertTrue(payload["is_active"])
        self.assertFalse(payload["is_revoked"])

    # 日本語: 共有リンクの有効期限と再発行の指定がサービス層へそのまま渡ることを検証します。
    # English: Verify that expiry and force-refresh options reach the service layer unchanged.
    def test_share_chat_room_forwards_expiry_and_force_refresh(self):
        request = make_share_request(
            {"room_id": "room-42", "expires_in_days": 7, "force_refresh": True},
            session={"user_id": 3},
        )

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms.validate_room_owner", return_value=(None, None)):
                with patch(
                    "blueprints.chat.rooms.create_or_get_shared_chat_token",
                    return_value=share_state(),
                ) as create_token:
                    response = asyncio.run(share_chat_room(request))

        self.assertEqual(response.status_code, 200)
        create_token.assert_awaited_once_with("room-42", 3, expires_in_days=7, force_refresh=True)

    # 日本語: 共有チャットルーム取得時にトークンが指定されていない場合に400エラーとなることを検証します。
    # English: Verify that accessing a shared chat room without a token returns 400.
    def test_shared_chat_room_requires_token(self):
        # 日本語: クエリパラメータにトークンを含めずにリクエストを作成
        # English: Create a request with no token in the query parameters
        request = build_request(
            method="GET",
            path="/api/shared_chat_room",
            query_string=b"",
            session={},
        )
        # 日本語: クリーニング処理をモック化してリクエストを実行
        # English: Mock the cleanup process and run the request
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            response = asyncio.run(shared_chat_room(request))

        # 日本語: 400エラーとエラー原因が返されることを確認
        # English: Assert that a 400 error and the error reason are returned
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "token is required")

    # 日本語: 有効なトークンが指定された場合に、共有されたチャットルームとメッセージ情報が取得できることを検証します。
    # English: Verify that a valid token returns the shared chat room details and its messages.
    def test_shared_chat_room_returns_payload(self):
        # 日本語: 有効なトークンを指定してリクエストを作成
        # English: Create a request with a valid token
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

        # 日本語: ペイロード取得処理をモック化して期待されるデータを返すように設定
        # English: Mock the payload retrieval process to return the expected data
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.get_shared_chat_room_payload",
                return_value=expected,
            ):
                response = asyncio.run(shared_chat_room(request))

        # 日本語: 正常にデータが取得できていることを確認
        # English: Assert successful retrieval of the correct details
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["room"]["id"], "room-1")
        self.assertEqual(payload["messages"][0]["message"], "こんにちは")

    # 日本語: 存在しない、または無効なトークンを指定した場合に404エラーとなることを検証します。
    # English: Verify that an invalid or non-existent token returns 404.
    def test_shared_chat_room_returns_not_found(self):
        # 日本語: 存在しないトークンを指定してリクエストを作成
        # English: Create a request with a non-existent token
        request = make_shared_read_request("missing")

        # 日本語: 共有リンクが見つからないエラーを返すようにモック化
        # English: Mock the shared room lookup to return a 404 error
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.get_shared_chat_room_payload",
                return_value=({"error": "共有リンクが見つかりません"}, 404),
            ):
                response = asyncio.run(shared_chat_room(request))

        # 日本語: 404エラーと適切なメッセージが返ることを確認
        # English: Assert 404 status and that the correct error message is returned
        self.assertEqual(response.status_code, 404)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "共有リンクが見つかりません")


# 日本語: チャット共有リンクの失効APIのユニットテスト
# English: Unit tests for the chat share-link revocation API
class ChatShareRevocationTestCase(unittest.TestCase):
    # 日本語: 未ログインのユーザーが共有リンクを失効できないことを検証します。
    # English: Verify that revoking a share link requires an authenticated session.
    def test_revoke_requires_login(self):
        request = make_revoke_request({"room_id": "room-1"}, session={})

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            response = asyncio.run(revoke_chat_room_share(request))

        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "ログインが必要です")

    # 日本語: 他ユーザーのチャットルームの共有リンクは失効できないことを検証します。
    # English: Verify that a non-owner cannot revoke someone else's share link.
    def test_revoke_returns_403_when_not_owner(self):
        request = make_revoke_request({"room_id": "room-1"}, session={"user_id": 10})

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.validate_room_owner",
                return_value=({"error": "他ユーザーのチャットルームは共有できません"}, 403),
            ):
                with patch("blueprints.chat.rooms.revoke_shared_chat_token") as revoke:
                    response = asyncio.run(revoke_chat_room_share(request))

        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "他ユーザーのチャットルームは共有できません")
        revoke.assert_not_awaited()

    # 日本語: 所有者が共有リンクを失効させると、共有URLが空になることを検証します。
    # English: Verify that a successful revocation clears the public share URL.
    def test_revoke_clears_share_url_on_success(self):
        request = make_revoke_request({"room_id": "room-42"}, session={"user_id": 3})
        revoked = share_state(revoked_at=datetime(2026, 9, 13, tzinfo=UTC).isoformat())

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms.validate_room_owner", return_value=(None, None)):
                with patch("blueprints.chat.rooms.revoke_shared_chat_token", return_value=revoked) as revoke:
                    response = asyncio.run(revoke_chat_room_share(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["is_revoked"])
        self.assertFalse(payload["is_active"])
        self.assertEqual(payload["share_url"], "")
        self.assertEqual(payload["message"], "共有リンクを無効にしました")
        revoke.assert_awaited_once_with("room-42", 3)

    # 日本語: 一度も共有していないルームの失効要求が404になることを検証します。
    # English: Verify that revoking a never-shared room reports 404.
    def test_revoke_returns_404_when_never_shared(self):
        request = make_revoke_request({"room_id": "room-42"}, session={"user_id": 3})

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms.validate_room_owner", return_value=(None, None)):
                with patch("blueprints.chat.rooms.revoke_shared_chat_token", return_value=None):
                    response = asyncio.run(revoke_chat_room_share(request))

        self.assertEqual(response.status_code, 404)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], ERROR_SHARED_LINK_NOT_FOUND)

    # 日本語: 一時チャットの共有リンクは失効操作の対象外であることを検証します。
    # English: Verify that temporary chats are rejected before any revocation write.
    def test_revoke_rejects_temporary_chat(self):
        request = make_revoke_request({"room_id": "room-42"}, session={"user_id": 3})

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms.ephemeral_store") as store:
                store.room_exists.return_value = True
                with patch("blueprints.chat.rooms.revoke_shared_chat_token") as revoke:
                    response = asyncio.run(revoke_chat_room_share(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "temporary chat は共有できません")
        revoke.assert_not_awaited()

    # 日本語: 失効済み・期限切れのトークンでは共有チャットを閲覧できないことを検証します。
    # English: Verify that revoked or expired tokens cannot load a shared chat.
    def test_revoked_or_expired_token_is_not_viewable(self):
        for label in ("revoked", "expired"):
            with self.subTest(link=label):
                request = make_shared_read_request("dead-token")
                with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
                    with patch(
                        "blueprints.chat.rooms.get_shared_chat_room_payload",
                        side_effect=ResourceNotFoundError(ERROR_SHARED_LINK_NOT_FOUND),
                    ):
                        response = asyncio.run(shared_chat_room(request))

                self.assertEqual(response.status_code, 404)
                payload = json.loads(response.body.decode("utf-8"))
                self.assertEqual(payload["error"], ERROR_SHARED_LINK_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
