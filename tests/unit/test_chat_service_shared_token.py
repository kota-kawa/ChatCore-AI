import unittest
from unittest.mock import patch

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.chat_service import create_or_get_shared_chat_token


# 日本語: PostgreSQLの一意性制約エラー（エラーコード: 23505）をシミュレートする疑似例外クラス。
# English: Mock exception class simulating PostgreSQL's unique key violation (error code: 23505).
class UniqueViolation(Exception):
    # 日本語: 例外オブジェクトを初期化し、PostgreSQLの重複エラーコードを設定します。
    # English: Initialize the exception object and set the PostgreSQL duplicate error code.
    def __init__(self):
        super().__init__("duplicate key")
        self.pgcode = "23505"


# 日本語: チャットルーム共有トークン生成ロジック（ルーム所有権、ON CONFLICT処理、一意性衝突リトライ等）をテストするための疑似DBカーソルクラス。
# English: Mock database cursor class for testing shared chat token creation, ownership check, ON CONFLICT, and collision retries.
class FakeCursor:
    # 日本語: 疑似カーソルを初期化します。ルーム所有者IDやインサート結果、失敗させる試行回数などを設定します。
    # English: Initialize the fake cursor with room owner ID, insertion results, and failure attempts.
    def __init__(self, *, room_owner_id=1, insert_results=None, fail_attempts=None):
        self.room_owner_id = room_owner_id
        self.insert_results = list(insert_results or [])
        self.fail_attempts = set(fail_attempts or [])
        self.executed = []
        self.insert_attempts = 0
        self.closed = False
        self._fetchone_result = None

    # 日本語: SQLクエリを実行し、引数および状態の変化を記録します。
    # English: Execute a SQL query, recording the arguments and changes to the state.
    def execute(self, query, params=None):
        # 日本語: 実行されたクエリとパラメータを記録
        # English: Record the executed query and parameters
        self.executed.append((query, params))
        normalized = " ".join(query.split())

        # 日本語: チャットルームの所有者検索をモック
        # English: Mock chat room owner lookup query
        if normalized == "SELECT user_id FROM chat_rooms WHERE id = %s":
            self._fetchone_result = None if self.room_owner_id is None else (self.room_owner_id,)
            return

        # 日本語: 共有エントリ追加クエリをモック（競合時にUniqueViolationを発生させる）
        # English: Mock shared room insertion query (raise UniqueViolation on configured attempts)
        if "INSERT INTO shared_chat_rooms" in normalized:
            self.insert_attempts += 1
            if self.insert_attempts in self.fail_attempts:
                raise UniqueViolation()

            if self.insert_results:
                token = self.insert_results.pop(0)
            else:
                token = params[1]
            self._fetchone_result = (token,)
            return

        raise AssertionError(f"Unexpected query: {normalized}")

    # 日本語: 最後に実行したクエリの取得結果（単一レコード）を返却します。
    # English: Return the fetch result (a single record) of the last executed query.
    def fetchone(self):
        return self._fetchone_result

    # 日本語: カーソルを閉じたフラグを設定します。
    # English: Set the flag indicating the cursor has been closed.
    def close(self):
        self.closed = True


# 日本語: チャットルーム共有トークン生成ロジックをテストするための疑似DBコネクションクラス。
# English: Mock database connection class for testing shared chat token creation.
class FakeConnection:
    # 日本語: 疑似コネクションを初期化し、関連するカーソルを設定します。
    # English: Initialize the fake connection and associate it with a cursor.
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False
        self.commit_calls = 0
        self.rollback_calls = 0

    # 日本語: 関連する疑似カーソルオブジェクトを返却します。
    # English: Return the associated fake cursor object.
    def cursor(self):
        return self._cursor

    # 日本語: コミット処理が呼び出された回数をカウントします。
    # English: Increment the counter for commit calls.
    def commit(self):
        self.commit_calls += 1

    # 日本語: ロールバック処理が呼び出された回数をカウントします。
    # English: Increment the counter for rollback calls.
    def rollback(self):
        self.rollback_calls += 1

    # 日本語: コネクションを閉じたフラグを設定します。
    # English: Set the flag indicating the connection has been closed.
    def close(self):
        self.closed = True

    # 日本語: コンテキストマネージャの開始時に自身を返却します。
    # English: Return self when entering the context manager.
    def __enter__(self):
        return self

    # 日本語: コンテキストマネージャの終了時にコネクションをクローズします。
    # English: Close the connection when leaving the context manager.
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# 日本語: チャットルームを公開共有するためのアクセストークン生成処理をテストするクラス。
# English: Test class to check the access token generation for public sharing of chat rooms.
class ChatServiceSharedTokenTestCase(unittest.TestCase):
    # 日本語: 指定されたチャットルームが存在しない場合に、ResourceNotFoundError(404)がスローされることを検証します。
    # English: Verify that a ResourceNotFoundError (404) is raised if the chat room does not exist.
    def test_create_or_get_shared_chat_token_raises_404_when_room_missing(self):
        # 日本語: ルーム所有者が存在しない（ルーム自体がない）カーソルとコネクションを準備
        # English: Prepare cursor and connection indicating no room owner (room missing)
        fake_cursor = FakeCursor(room_owner_id=None)
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: データベース接続をモックしてトークン生成関数を呼び出し、404エラーを検証
        # English: Mock the database connection, invoke the token creation, and verify 404 error
        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ResourceNotFoundError) as exc_info:
                create_or_get_shared_chat_token("missing-room", 10)

        # 日本語: エラーのステータスコードとメッセージ、接続が適切に閉じられたかを検証
        # English: Assert the error status, message, and that connections are closed properly
        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertEqual(exc_info.exception.message, "該当ルームが見つかりません")
        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    # 日本語: 他人の所有するチャットルームを共有しようとした場合に、ForbiddenOperationError(403)がスローされることを検証します。
    # English: Verify that a ForbiddenOperationError (403) is raised if trying to share a chat room owned by another user.
    def test_create_or_get_shared_chat_token_raises_403_when_room_is_not_owned(self):
        # 日本語: ルーム所有者のIDがリクエスト者(10)と異なる(99)状態を準備
        # English: Prepare state where the room owner (99) is different from the requester (10)
        fake_cursor = FakeCursor(room_owner_id=99)
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: データベース接続をモックしてトークン生成関数を呼び出し、403エラーを検証
        # English: Mock the database connection, invoke the token creation, and verify 403 error
        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ForbiddenOperationError) as exc_info:
                create_or_get_shared_chat_token("room-1", 10)

        # 日本語: 403エラーとエラーメッセージ、および接続クローズ状況を検証
        # English: Assert 403 status, error message, and connection closure
        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.message, "他ユーザーのチャットルームは共有できません")
        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    # 日本語: すでに共有トークンが存在する場合、ON CONFLICT句により既存のトークンが再利用（取得）されることを検証します。
    # English: Verify that an existing share token is reused (returned) by leveraging the ON CONFLICT clause.
    def test_create_or_get_shared_chat_token_uses_on_conflict_and_reuses_existing_token(self):
        # 日本語: すでに存在する共有トークンを返すように設定された疑似カーソルを準備
        # English: Prepare fake cursor configured to return an existing share token
        fake_cursor = FakeCursor(room_owner_id=3, insert_results=["existing-share-token"])
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: DB接続とトークン生成モジュールをモックして実行
        # English: Mock database connection and token generator, then run the target function
        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with patch("services.chat_service.secrets.token_urlsafe", return_value="new-token"):
                token = create_or_get_shared_chat_token("room-1", 3)

        # 日本語: 既存のトークンが返されること、ON CONFLICTを含むクエリが実行されたことを検証
        # English: Assert existing token is returned and query contains ON CONFLICT clause
        self.assertEqual(token, "existing-share-token")
        self.assertEqual(fake_connection.commit_calls, 1)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertEqual(len(fake_cursor.executed), 2)
        self.assertIn("ON CONFLICT (chat_room_id)", fake_cursor.executed[1][0])
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    # 日本語: トークン追加時のランダムトークン重複競合時に、自動的に別トークンで再生成・リトライされ成功することを検証します。
    # English: Verify that a token collision triggers a retry with a freshly generated token, which then succeeds.
    def test_create_or_get_shared_chat_token_retries_on_unique_token_collision(self):
        # 日本語: 1回目の追加試行は失敗し、2回目は成功してfresh-tokenを返すように設定
        # English: Configure 1st insertion to fail and 2nd to succeed returning 'fresh-token'
        fake_cursor = FakeCursor(
            room_owner_id=5,
            insert_results=["fresh-token"],
            fail_attempts={1},
        )
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: 最初のインサート試行で衝突が発生し、再試行で新鮮なトークンが適用される
        # English: First attempt colliding, retrying to insert with a fresh token
        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with patch(
                "services.chat_service.secrets.token_urlsafe",
                side_effect=["colliding-token", "fresh-token"],
            ):
                token = create_or_get_shared_chat_token("room-1", 5)

        # 日本語: 再試行後のトークンが取得できていること、ロールバックとコミットの回数を検証
        # English: Assert the token returned is the fresh one, and verify rollback/commit counts
        self.assertEqual(token, "fresh-token")
        self.assertEqual(fake_cursor.insert_attempts, 2)
        self.assertEqual(fake_connection.rollback_calls, 1)
        self.assertEqual(fake_connection.commit_calls, 1)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)


if __name__ == "__main__":
    unittest.main()
