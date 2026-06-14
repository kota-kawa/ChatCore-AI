import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from blueprints.chat.messages import chat
from blueprints.chat.rooms import _encode_room_list_cursor, _fetch_persisted_user_rooms, get_chat_rooms, new_chat_room
from starlette.responses import StreamingResponse
from tests.helpers.request_helpers import build_request


# 日本語: チャットの一時的モード（データベースへ保存しないモード）の機能および仕様を検証するテストクラス。
# English: Test case class to verify the functionality and specifications of Chat Temporary Mode (non-persisted mode).
class ChatTemporaryModeTestCase(unittest.TestCase):
    # 日本語: モードに 'temporary' が指定された際、DBではなく一時ストア(エフェメラルストア)上にチャットルームが作成されることを検証します。
    # English: Verify that specifying 'temporary' mode creates the chat room in the ephemeral store instead of the database.
    def test_new_chat_room_creates_temporary_authenticated_room_without_db_persistence(self):
        # 日本語: ログインユーザー（user_id: 7）かつ temporary モードのルーム作成要求を作成
        # English: Create a room creation request with temporary mode for a logged-in user (user ID 7)
        request = build_request(
            method="POST",
            path="/api/new_chat_room",
            json_body={"id": "temp-room", "title": "Temp", "mode": "temporary"},
            session={"user_id": 7},
        )

        # 日本語: DBへの追加処理と一時ストア(エフェメラルストア)への追加処理をモック化
        # English: Mock DB room creation and ephemeral store creation
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms.create_chat_room_in_db") as create_room:
                with patch("blueprints.chat.rooms.ephemeral_store.create_room") as create_ephemeral:
                    response = asyncio.run(new_chat_room(request))

        # 日本語: DB保存処理は呼ばれず、一時ストア側に専用のプレフィックス付きキーで作成されていることを検証
        # English: Assert that DB creation is not called, and creation occurs in ephemeral store with temporary prefix
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["mode"], "temporary")
        create_room.assert_not_called()
        create_ephemeral.assert_called_once_with("temporary-user:7", "temp-room", "Temp")

    # 日本語: チャットルーム一覧取得APIにおいて、一時ストアではなく、DBに永続化された通常のチャットルームのみが返ることを検証します。
    # English: Verify that get chat rooms API returns only normal, DB-persisted rooms and excludes temporary ones.
    def test_get_chat_rooms_returns_only_persisted_rooms(self):
        # 日本語: ログインユーザー（user_id: 7）でチャットルーム取得リクエストを作成
        # English: Create a get chat rooms request for a logged-in user (user ID 7)
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

        # 日本語: DBからのフェッチ処理をモックして検証を実行
        # English: Mock DB fetch and execute the request
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms._fetch_persisted_user_rooms", return_value=persisted_rooms):
                response = asyncio.run(get_chat_rooms(request))

        # 日本語: 返されたルーム一覧にDBに保存されていたルームのみが含まれていることを検証
        # English: Assert that only the DB-persisted room is returned in the response
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual([room["id"] for room in payload["rooms"]], ["room-normal"])

    # 日本語: ページネーション時、カーソルを用いて永続化されたチャットルーム一覧を正しく取得できることを検証します。
    # English: Verify that get chat rooms API paginates persisted rooms using cursors correctly.
    def test_get_chat_rooms_paginates_persisted_rooms_with_cursor(self):
        # 日本語: limit=20 を指定してチャットルーム一覧取得リクエストを作成
        # English: Create a get chat rooms request specifying limit=20
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

        # 日本語: DBフェッチ処理をモックし、limit+1件(21件)のルームがある状況をシミュレート
        # English: Mock DB fetch, simulating a scenario where limit+1 (21) rooms exist
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms._fetch_persisted_user_rooms", return_value=persisted_rooms) as fetch_rooms:
                response = asyncio.run(get_chat_rooms(request))

        # 日本語: 20件が返却され、has_moreがTrueであり、next_cursorが設定されていることを確認
        # English: Assert that 20 rooms are returned, has_more is True, and next_cursor is populated
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(len(payload["rooms"]), 20)
        self.assertTrue(payload["pagination"]["has_more"])
        self.assertIsInstance(payload["pagination"]["next_cursor"], str)
        self.assertNotIn("next_offset", payload["pagination"])
        fetch_rooms.assert_called_once_with(7, limit=21, cursor=None)

    # 日本語: 暗号化/エンコードされたカーソルパラメータが、デコードされて内部のフェッチ関数へ渡されることを検証します。
    # English: Verify that the encoded cursor parameter is decoded and passed to the internal room fetching function.
    def test_get_chat_rooms_passes_decoded_cursor_to_fetch(self):
        # 日本語: テスト用のデコード前カーソルを作成
        # English: Encode a mock cursor for testing
        cursor = _encode_room_list_cursor(
            {"id": "room-20", "created_at": "2026-04-20T10:00:00"}
        )
        request = build_request(
            method="GET",
            path="/api/get_chat_rooms",
            query_string=f"limit=20&cursor={cursor}".encode("utf-8"),
            session={"user_id": 7},
        )

        # 日本語: DBからの取得処理をモック化して実行
        # English: Mock DB room fetch and execute the request
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms._fetch_persisted_user_rooms", return_value=[]) as fetch_rooms:
                response = asyncio.run(get_chat_rooms(request))

        # 日本語: フェッチ関数呼び出し時に、デコードされた日時とルームIDが渡されていることを検証
        # English: Assert that the fetch function is called with the decoded datetime and room ID
        self.assertEqual(response.status_code, 200)
        fetch_rooms.assert_called_once_with(
            7,
            limit=21,
            cursor=(datetime(2026, 4, 20, 10, 0, 0), "room-20"),
        )

    # 日本語: 無効または不正なフォーマットのカーソルが指定された際、400エラーが返されることを検証します。
    # English: Verify that specifying an invalid or malformed cursor returns a 400 error.
    def test_get_chat_rooms_rejects_invalid_cursor(self):
        # 日本語: 不正な cursor="invalid" クエリパラメータを指定してリクエストを作成
        # English: Create a request with an invalid cursor query parameter
        request = build_request(
            method="GET",
            path="/api/get_chat_rooms",
            query_string=b"limit=20&cursor=invalid",
            session={"user_id": 7},
        )

        # 日本語: クリーニングおよびDB取得処理をモック化
        # English: Mock cleanup and DB fetch functions
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms._fetch_persisted_user_rooms") as fetch_rooms:
                response = asyncio.run(get_chat_rooms(request))

        # 日本語: 400エラーが返され、DBフェッチ処理が呼び出されていないことを検証
        # English: Assert status is 400 and that the DB fetch function was not invoked
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "invalid cursor")
        fetch_rooms.assert_not_called()

    # 日本語: 永続化されたルーム取得クエリが、一貫性のある安定したキーセットベース（created_atとidの組み合わせ）のソート・取得を行うことを検証します。
    # English: Verify that the query to fetch persisted rooms uses a stable keyset-based order and condition (created_at and id).
    def test_fetch_persisted_user_rooms_uses_stable_keyset_query(self):
        # 日本語: テスト用の疑似DBカーソルクラス
        # English: Mock database cursor class for testing
        class Cursor:
            # 日本語: クエリとパラメータの記録領域を初期化します。
            # English: Initialize query and parameters storage.
            def __init__(self):
                self.query = ""
                self.params = ()

            # 日本語: 実行されたクエリおよびパラメータを記録します。
            # English: Record the query and parameters executed.
            def execute(self, query, params):
                self.query = query
                self.params = params

            # 日本語: テスト用のレコード取得結果を返却します。
            # English: Return mock record results.
            def fetchall(self):
                return [("room-21", "Room 21", "normal", datetime(2026, 4, 19, 10, 0, 0))]

            # 日本語: カーソルを閉じます。
            # English: Close the cursor.
            def close(self):
                pass

        # 日本語: テスト用の疑似DB接続クラス
        # English: Mock database connection class for testing
        class Connection:
            # 日本語: 疑似カーソルをインスタンス化して初期化します。
            # English: Instantiate and initialize the fake cursor.
            def __init__(self):
                self.cursor_instance = Cursor()

            # 日本語: 疑似カーソルを返却します。
            # English: Return the fake cursor.
            def cursor(self):
                return self.cursor_instance

            # 日本語: 接続を閉じます。
            # English: Close the connection.
            def close(self):
                pass

        connection = Connection()
        cursor_value = (datetime(2026, 4, 20, 10, 0, 0), "room-20")

        # 日本語: データベース接続をモックして永続ルーム取得処理を実行
        # English: Mock database connection and run fetch_persisted_user_rooms
        with patch("blueprints.chat.rooms.get_db_connection", return_value=connection):
            rooms = _fetch_persisted_user_rooms(7, limit=21, cursor=cursor_value)

        # 日本語: 取得結果が正しいこと、および生成されたSQLがキーセットによる比較と降順ソートを含んでいることを検証
        # English: Assert return value matches, and sql query includes keyset pagination logic and desc ordering
        self.assertEqual([room["id"] for room in rooms], ["room-21"])
        self.assertIn("AND (created_at, id) < (%s, %s)", connection.cursor_instance.query)
        self.assertIn("ORDER BY created_at DESC, id DESC", connection.cursor_instance.query)
        self.assertEqual(connection.cursor_instance.params, (7, cursor_value[0], "room-20", 21))

    # 日本語: ログイン済みユーザーの一時チャットルームでの会話が、DBではなく一時ストア(エフェメラルストア)を使用することを検証します。
    # English: Verify that chat in an authenticated temporary room is saved to the ephemeral store rather than the DB.
    def test_chat_uses_ephemeral_store_for_authenticated_temporary_room(self):
        # 日本語: 一時チャットルーム宛の新規メッセージリクエストを作成
        # English: Create a new chat request targeting a temporary chat room
        request = build_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "temp-room", "model": "gpt-5-mini"},
            session={"user_id": 11},
        )

        # 日本語: 所有権検証、一時ストアへの追加や読み取り、LLMとのやり取りなどをモック化して実行
        # English: Mock ownership, ephemeral store get/append, LLM logic, and quota checks
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

        # 日本語: レスポンスが正常終了し、エフェメラルストアへの追記(ユーザー入力とAI回答)が行われたことを検証
        # English: Assert success status, expected mock response, and append_message called for user/AI
        self.assertNotIsInstance(response, StreamingResponse)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "やあ")
        self.assertGreaterEqual(append_message.call_count, 2)


if __name__ == "__main__":
    unittest.main()
