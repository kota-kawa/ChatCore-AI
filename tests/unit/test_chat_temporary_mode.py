import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from blueprints.chat.messages import chat
from blueprints.chat.rooms import _encode_room_list_cursor, _fetch_persisted_user_rooms, get_chat_rooms, new_chat_room
from starlette.responses import StreamingResponse
from tests.helpers.request_helpers import build_request


# 日本語: Chat Temporary Modeの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Chat Temporary Mode.
class ChatTemporaryModeTestCase(unittest.TestCase):
    # 日本語: DBpersistenceを使用しない場合、newチャットroom作成する一時的authenticatedroomことを検証します。
    # English: Verify that new chat room creates temporary authenticated room without db persistence.
    def test_new_chat_room_creates_temporary_authenticated_room_without_db_persistence(self):
        request = build_request(
            method="POST",
            path="/api/new_chat_room",
            json_body={"id": "temp-room", "title": "Temp", "mode": "temporary"},
            session={"user_id": 7},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms.create_chat_room_in_db") as create_room:
                with patch("blueprints.chat.rooms.ephemeral_store.create_room") as create_ephemeral:
                    response = asyncio.run(new_chat_room(request))

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["mode"], "temporary")
        create_room.assert_not_called()
        create_ephemeral.assert_called_once_with("temporary-user:7", "temp-room", "Temp")

    # 日本語: getチャットルーム返却するonlypersistedルームことを検証します。
    # English: Verify that get chat rooms returns only persisted rooms.
    def test_get_chat_rooms_returns_only_persisted_rooms(self):
        request = build_request(
            method="GET",
            path="/api/get_chat_rooms",
            session={"user_id": 7},
        )

        persisted_rooms = [
            {
                "id": "room-normal",
                "title": "保存チャット",
                "mode": "normal",
                "created_at": "2026-04-20T10:00:00+09:00",
            }
        ]

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms._fetch_persisted_user_rooms", return_value=persisted_rooms):
                response = asyncio.run(get_chat_rooms(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual([room["id"] for room in payload["rooms"]], ["room-normal"])

    # 日本語: cursorを使用する場合、getチャットルームpaginatespersistedルームことを検証します。
    # English: Verify that get chat rooms paginates persisted rooms with cursor.
    def test_get_chat_rooms_paginates_persisted_rooms_with_cursor(self):
        request = build_request(
            method="GET",
            path="/api/get_chat_rooms",
            query_string=b"limit=20",
            session={"user_id": 7},
        )

        persisted_rooms = [
            {
                "id": f"room-{index}",
                "title": f"Room {index}",
                "mode": "normal",
                "created_at": "2026-04-20T10:00:00+09:00",
            }
            for index in range(21)
        ]

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms._fetch_persisted_user_rooms", return_value=persisted_rooms) as fetch_rooms:
                response = asyncio.run(get_chat_rooms(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(len(payload["rooms"]), 20)
        self.assertTrue(payload["pagination"]["has_more"])
        self.assertIsInstance(payload["pagination"]["next_cursor"], str)
        self.assertNotIn("next_offset", payload["pagination"])
        fetch_rooms.assert_called_once_with(7, limit=21, cursor=None)

    # 日本語: fetchへ、getチャットルーム通過するdecodedcursorことを検証します。
    # English: Verify that get chat rooms passes decoded cursor to fetch.
    def test_get_chat_rooms_passes_decoded_cursor_to_fetch(self):
        cursor = _encode_room_list_cursor(
            {"id": "room-20", "created_at": "2026-04-20T10:00:00"}
        )
        request = build_request(
            method="GET",
            path="/api/get_chat_rooms",
            query_string=f"limit=20&cursor={cursor}".encode("utf-8"),
            session={"user_id": 7},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms._fetch_persisted_user_rooms", return_value=[]) as fetch_rooms:
                response = asyncio.run(get_chat_rooms(request))

        self.assertEqual(response.status_code, 200)
        fetch_rooms.assert_called_once_with(
            7,
            limit=21,
            cursor=(datetime(2026, 4, 20, 10, 0, 0), "room-20"),
        )

    # 日本語: getチャットルーム拒否する無効なcursorことを検証します。
    # English: Verify that get chat rooms rejects invalid cursor.
    def test_get_chat_rooms_rejects_invalid_cursor(self):
        request = build_request(
            method="GET",
            path="/api/get_chat_rooms",
            query_string=b"limit=20&cursor=invalid",
            session={"user_id": 7},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms._fetch_persisted_user_rooms") as fetch_rooms:
                response = asyncio.run(get_chat_rooms(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "invalid cursor")
        fetch_rooms.assert_not_called()

    # 日本語: fetchpersistedユーザールームusesstablekeysetクエリことを検証します。
    # English: Verify that fetch persisted user rooms uses stable keyset query.
    def test_fetch_persisted_user_rooms_uses_stable_keyset_query(self):
        # 日本語: テスト用のCursorクラスです。
# English: Cursor class for testing.
        class Cursor:
            # 日本語: インスタンス生成時に必要な初期状態を設定します。
            # English: Initialize the required instance state when the object is created.
            def __init__(self):
                self.query = ""
                self.params = ()

            # 日本語: execute の実行処理を担当します。
            # English: Handle executing for execute.
            def execute(self, query, params):
                self.query = query
                self.params = params

            # 日本語: テスト用の処理の入口関数fetchallです。
# English: Entry point helper function fetchall for testing.
            def fetchall(self):
                return [("room-21", "Room 21", "normal", datetime(2026, 4, 19, 10, 0, 0))]

            # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
            def close(self):
                pass

        # 日本語: テスト用のConnectionクラスです。
# English: Connection class for testing.
        class Connection:
            # 日本語: インスタンス生成時に必要な初期状態を設定します。
            # English: Initialize the required instance state when the object is created.
            def __init__(self):
                self.cursor_instance = Cursor()

            # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
            def cursor(self):
                return self.cursor_instance

            # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
            def close(self):
                pass

        connection = Connection()
        cursor_value = (datetime(2026, 4, 20, 10, 0, 0), "room-20")

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.rooms.get_db_connection", return_value=connection):
            rooms = _fetch_persisted_user_rooms(7, limit=21, cursor=cursor_value)

        self.assertEqual([room["id"] for room in rooms], ["room-21"])
        self.assertIn("AND (created_at, id) < (%s, %s)", connection.cursor_instance.query)
        self.assertIn("ORDER BY created_at DESC, id DESC", connection.cursor_instance.query)
        self.assertEqual(connection.cursor_instance.params, (7, cursor_value[0], "room-20", 21))

    # 日本語: authenticated一時的roomに対して、チャットusesエフェメラルストアことを検証します。
    # English: Verify that chat uses ephemeral store for authenticated temporary room.
    def test_chat_uses_ephemeral_store_for_authenticated_temporary_room(self):
        request = build_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "temp-room", "model": "gpt-5-mini"},
            session={"user_id": 11},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with (
            patch("blueprints.chat.messages.cleanup_ephemeral_chats"),
            patch("blueprints.chat.messages.validate_room_owner", return_value="temporary"),
            patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True),
            patch("blueprints.chat.messages.ephemeral_store.append_message") as append_message,
            patch(
                "blueprints.chat.messages.ephemeral_store.get_messages",
                return_value=[{"role": "user", "content": "こんにちは"}],
            ),
            patch("blueprints.chat.messages.get_user_by_id", return_value={}),
            patch(
                "blueprints.chat.messages.consume_llm_daily_quota",
                return_value=(True, 1, 300),
            ),
            patch("blueprints.chat.messages.is_streaming_model", return_value=False),
            patch("blueprints.chat.messages.get_llm_response", return_value="やあ"),
        ):
            response = asyncio.run(chat(request))

        self.assertNotIsInstance(response, StreamingResponse)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "やあ")
        self.assertGreaterEqual(append_message.call_count, 2)


if __name__ == "__main__":
    unittest.main()
