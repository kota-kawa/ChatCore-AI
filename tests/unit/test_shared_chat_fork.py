import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.rooms import fork_shared_chat_room
from services.api_errors import ResourceNotFoundError
from services.shared_chat_fork import (
    MAX_FORKED_MESSAGES,
    fork_shared_chat_into_db_room,
    fork_shared_chat_into_ephemeral_room,
)
from tests.helpers.request_helpers import build_request


SHARED_PAYLOAD = {
    "room": {"id": "room-1", "title": "共有された会話", "created_at": "2026-08-01T00:00:00+00:00"},
    "messages": [
        {"message": "こんにちは", "sender": "user", "timestamp": "2026-08-01T00:00:01+00:00"},
        {
            "message": "はい、どうぞ",
            "sender": "assistant",
            "timestamp": "2026-08-01T00:00:02+00:00",
            "message_parts": [{"type": "text", "text": "はい、どうぞ"}],
        },
    ],
}


# 日本語: 複製リクエストを作成するヘルパー関数
# English: Helper that builds a fork request
def make_fork_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/fork_shared_chat_room",
        json_body=json_body,
        session=session if session is not None else {},
    )


# 日本語: エフェメラルストアの複製先を記録するだけのテスト用スタブ
# English: Test stub that records what the fork writes into the ephemeral store
class RecordingEphemeralStore:
    def __init__(self):
        self.rooms = {}
        self.messages = []

    def create_room(self, sid, room_id, title):
        self.rooms[(sid, room_id)] = title

    def append_message(self, sid, room_id, role, content, message_parts=None, **_kwargs):
        self.messages.append(
            {"sid": sid, "room_id": room_id, "role": role, "content": content, "message_parts": message_parts}
        )
        return True


# 日本語: 共有チャット複製サービスのユニットテスト
# English: Unit tests for the shared chat fork service
class SharedChatForkServiceTestCase(unittest.TestCase):
    # 日本語: ログインユーザー向けの複製で、通常ルーム作成とメッセージ複製が呼ばれることを検証します。
    # English: Verify the authenticated fork creates a normal room and copies the messages into it.
    def test_fork_into_db_room_copies_messages_in_order(self):
        with patch(
            "services.shared_chat_fork.get_shared_chat_room_payload",
            return_value=SHARED_PAYLOAD,
        ):
            with patch("services.shared_chat_fork.create_chat_room_in_db") as create_room:
                with patch(
                    "services.shared_chat_fork.copy_messages_into_chat_room",
                    return_value=2,
                ) as copy_messages:
                    result = fork_shared_chat_into_db_room("token-1", "room-new", 7)

        create_room.assert_called_once_with("room-new", 7, "共有された会話", "normal")
        copied_messages = copy_messages.call_args[0][1]
        self.assertEqual([message["sender"] for message in copied_messages], ["user", "assistant"])
        self.assertEqual(
            result,
            {"id": "room-new", "title": "共有された会話", "mode": "normal", "message_count": 2},
        )

    # 日本語: 非ログインユーザー向けの複製が、エフェメラルストアへ role 付きで書き込まれることを検証します。
    # English: Verify the guest fork writes role-tagged messages into the ephemeral store.
    def test_fork_into_ephemeral_room_writes_roles(self):
        store = RecordingEphemeralStore()

        with patch(
            "services.shared_chat_fork.get_shared_chat_room_payload",
            return_value=SHARED_PAYLOAD,
        ):
            result = fork_shared_chat_into_ephemeral_room("token-1", "sid-1", "room-new", store)

        self.assertEqual(store.rooms[("sid-1", "room-new")], "共有された会話")
        self.assertEqual([message["role"] for message in store.messages], ["user", "assistant"])
        self.assertEqual(store.messages[1]["message_parts"], [{"type": "text", "text": "はい、どうぞ"}])
        self.assertEqual(result["mode"], "temporary")
        self.assertEqual(result["message_count"], 2)

    # 日本語: 極端に長い共有チャットでも、複製件数が上限で頭打ちになることを検証します。
    # English: Verify an extremely long shared chat is truncated at the copy limit.
    def test_fork_truncates_at_the_message_limit(self):
        long_payload = {
            "room": {"title": "長い会話"},
            "messages": [
                {"message": f"m{index}", "sender": "user"}
                for index in range(MAX_FORKED_MESSAGES + 25)
            ],
        }
        store = RecordingEphemeralStore()

        with patch(
            "services.shared_chat_fork.get_shared_chat_room_payload",
            return_value=long_payload,
        ):
            result = fork_shared_chat_into_ephemeral_room("token-1", "sid-1", "room-new", store)

        self.assertEqual(result["message_count"], MAX_FORKED_MESSAGES)
        self.assertEqual(len(store.messages), MAX_FORKED_MESSAGES)


# 日本語: 共有チャット複製APIエンドポイントのユニットテスト
# English: Unit tests for the shared chat fork API endpoint
class ForkSharedChatRoomRouteTestCase(unittest.TestCase):
    # 日本語: ログインユーザーは自分の通常ルームとして複製できることを検証します。
    # English: Verify an authenticated viewer forks into a persisted normal room of their own.
    def test_authenticated_viewer_forks_into_own_room(self):
        request = make_fork_request({"token": "token-1", "id": "room-new"}, session={"user_id": 42})

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.fork_shared_chat_into_db_room",
                return_value={"id": "room-new", "title": "共有された会話", "mode": "normal", "message_count": 2},
            ) as fork_into_db:
                response = asyncio.run(fork_shared_chat_room(request))

        fork_into_db.assert_called_once_with("token-1", "room-new", 42)
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["mode"], "normal")

    # 日本語: 非ログインユーザーも一時ルームとして複製でき、セッションに登録されることを検証します。
    # English: Verify a guest forks into a temporary room that is registered in the session.
    def test_guest_viewer_forks_into_temporary_room(self):
        # build_request は空辞書を渡すと別の辞書に差し替えるため、セッションIDを入れて同一性を保つ。
        # build_request replaces a falsy session with a new dict, so seed it to keep the same object.
        session = {"sid": "sid-1"}
        request = make_fork_request({"token": "token-1", "id": "room-new"}, session=session)

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.consume_guest_chat_daily_limit",
                return_value=(True, ""),
            ):
                with patch(
                    "blueprints.chat.rooms.fork_shared_chat_into_ephemeral_room",
                    return_value={"id": "room-new", "title": "共有された会話", "mode": "temporary", "message_count": 2},
                ):
                    response = asyncio.run(fork_shared_chat_room(request))

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["mode"], "temporary")
        self.assertIn("room-new", session.get("guest_room_ids", []))

    # 日本語: ゲストの日次上限に達している場合は429を返し、複製を行わないことを検証します。
    # English: Verify the guest daily quota blocks the fork with 429 and copies nothing.
    def test_guest_viewer_is_rate_limited(self):
        request = make_fork_request({"token": "token-1", "id": "room-new"}, session={})

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.consume_guest_chat_daily_limit",
                return_value=(False, "1日10回までです"),
            ):
                with patch(
                    "blueprints.chat.rooms.fork_shared_chat_into_ephemeral_room",
                ) as fork_into_ephemeral:
                    response = asyncio.run(fork_shared_chat_room(request))

        fork_into_ephemeral.assert_not_called()
        self.assertEqual(response.status_code, 429)

    # 日本語: 無効なトークンでは404を返すことを検証します。
    # English: Verify an unknown share token results in a 404 response.
    def test_unknown_token_returns_not_found(self):
        request = make_fork_request({"token": "missing", "id": "room-new"}, session={"user_id": 1})

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.rooms.fork_shared_chat_into_db_room",
                side_effect=ResourceNotFoundError("共有リンクが見つかりません"),
            ):
                response = asyncio.run(fork_shared_chat_room(request))

        self.assertEqual(response.status_code, 404)

    # 日本語: token が空のリクエストはバリデーションエラーになることを検証します。
    # English: Verify a request without a token fails validation.
    def test_missing_token_is_rejected(self):
        request = make_fork_request({"id": "room-new"}, session={"user_id": 1})

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            response = asyncio.run(fork_shared_chat_room(request))

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
