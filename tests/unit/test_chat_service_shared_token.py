import unittest
from unittest.mock import patch

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.chat_service import create_or_get_shared_chat_token


# PostgreSQLの一意性制約エラー（エラーコード: 23505）をシミュレートする疑似例外クラス。
# Mock exception class simulating PostgreSQL's unique key violation (error code: 23505).
class UniqueViolation(Exception):
    # インスタンス生成時に必要な初期状態を設定します。
    # Initialize the required instance state when the object is created.
    def __init__(self):
        super().__init__("duplicate key")
        self.pgcode = "23505"


# チャットルーム共有トークン生成ロジック（ルーム所有権、ON CONFLICT処理、一意性衝突リトライ等）をテストするための疑似DBカーソルクラス。
# Mock database cursor class for testing shared chat token creation, ownership check, ON CONFLICT, and collision retries.
class FakeCursor:
    # インスタンス生成時に必要な初期状態を設定します。
    # Initialize the required instance state when the object is created.
    def __init__(self, *, room_owner_id=1, insert_results=None, fail_attempts=None):
        self.room_owner_id = room_owner_id
        self.insert_results = list(insert_results or [])
        self.fail_attempts = set(fail_attempts or [])
        self.executed = []
        self.insert_attempts = 0
        self.closed = False
        self._fetchone_result = None

    # クエリを実行し、引数および状態の変化を記録します。
    # Execute a query and track/log the execution arguments.
    def execute(self, query, params=None):
        self.executed.append((query, params))
        normalized = " ".join(query.split())

        # チャットルームの所有者検索をモック
        # Mock chat room owner lookup query
        if normalized == "SELECT user_id FROM chat_rooms WHERE id = %s":
            self._fetchone_result = None if self.room_owner_id is None else (self.room_owner_id,)
            return

        # 共有エントリ追加クエリをモック（競合時にUniqueViolationを発生させる）
        # Mock shared room insertion query (raise UniqueViolation on configured attempts)
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

    # レコードの取得結果を返却します。
    # Return fetch result.
    def fetchone(self):
        return self._fetchone_result

    # カーソルを閉じます。
    # Close the cursor.
    def close(self):
        self.closed = True


# チャットルーム共有トークン生成ロジックをテストするための疑似DBコネクションクラス。
# Mock database connection class for testing shared chat token creation.
class FakeConnection:
    # インスタンス生成時に必要な初期状態を設定します。
    # Initialize the required instance state when the object is created.
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False
        self.commit_calls = 0
        self.rollback_calls = 0

    # カーソルを返却します。
    # Return the cursor.
    def cursor(self):
        return self._cursor

    # コミットされた回数を記録します。
    # Record commit execution count.
    def commit(self):
        self.commit_calls += 1

    # ロールバックされた回数を記録します。
    # Record rollback execution count.
    def rollback(self):
        self.rollback_calls += 1

    # コネクションを閉じます。
    # Close the connection.
    def close(self):
        self.closed = True

    # コンテキスト開始時に必要な準備を行います。
    # Prepare the object when entering the context.
    def __enter__(self):
        return self

    # コンテキスト終了時の後片付けを行います。
    # Clean up when leaving the context.
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# チャットルームを公開共有するためのアクセストークン生成処理をテストするクラス。
# Test class to check the access token generation for public sharing of chat rooms.
class ChatServiceSharedTokenTestCase(unittest.TestCase):
    # 指定されたチャットルームが存在しない場合に、ResourceNotFoundError(404)がスローされることを検証します。
    # Verify that a ResourceNotFoundError (404) is raised if the chat room does not exist.
    def test_create_or_get_shared_chat_token_raises_404_when_room_missing(self):
        fake_cursor = FakeCursor(room_owner_id=None)
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ResourceNotFoundError) as exc_info:
                create_or_get_shared_chat_token("missing-room", 10)

        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertEqual(exc_info.exception.message, "該当ルームが見つかりません")
        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    # 他人の所有するチャットルームを共有しようとした場合に、ForbiddenOperationError(403)がスローされることを検証します。
    # Verify that a ForbiddenOperationError (403) is raised if trying to share a chat room owned by another user.
    def test_create_or_get_shared_chat_token_raises_403_when_room_is_not_owned(self):
        fake_cursor = FakeCursor(room_owner_id=99)
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ForbiddenOperationError) as exc_info:
                create_or_get_shared_chat_token("room-1", 10)

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.message, "他ユーザーのチャットルームは共有できません")
        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    # すでに共有トークンが存在する場合、ON CONFLICT句により既存のトークンが再利用（取得）されることを検証します。
    # Verify that an existing share token is reused (returned) by leveraging the ON CONFLICT clause.
    def test_create_or_get_shared_chat_token_uses_on_conflict_and_reuses_existing_token(self):
        fake_cursor = FakeCursor(room_owner_id=3, insert_results=["existing-share-token"])
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with patch("services.chat_service.secrets.token_urlsafe", return_value="new-token"):
                token = create_or_get_shared_chat_token("room-1", 3)

        self.assertEqual(token, "existing-share-token")
        self.assertEqual(fake_connection.commit_calls, 1)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertEqual(len(fake_cursor.executed), 2)
        self.assertIn("ON CONFLICT (chat_room_id)", fake_cursor.executed[1][0])
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    # トークン追加時のランダムトークン重複競合時に、自動的に別トークンで再生成・リトライされ成功することを検証します。
    # Verify that a token collision triggers a retry with a freshly generated token, which then succeeds.
    def test_create_or_get_shared_chat_token_retries_on_unique_token_collision(self):
        fake_cursor = FakeCursor(
            room_owner_id=5,
            insert_results=["fresh-token"],
            fail_attempts={1},
        )
        fake_connection = FakeConnection(fake_cursor)

        # 最初のインサート試行で衝突が発生し、再試行で新鮮なトークンが適用される
        # First attempt colliding, retrying to insert with a fresh token
        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with patch(
                "services.chat_service.secrets.token_urlsafe",
                side_effect=["colliding-token", "fresh-token"],
            ):
                token = create_or_get_shared_chat_token("room-1", 5)

        self.assertEqual(token, "fresh-token")
        self.assertEqual(fake_cursor.insert_attempts, 2)
        self.assertEqual(fake_connection.rollback_calls, 1)
        self.assertEqual(fake_connection.commit_calls, 1)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)


if __name__ == "__main__":
    unittest.main()
