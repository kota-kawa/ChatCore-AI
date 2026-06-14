import unittest
from unittest.mock import patch

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.chat_service import create_or_get_shared_chat_token


# 日本語: UniqueViolation に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to UniqueViolation.
class UniqueViolation(Exception):
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        super().__init__("duplicate key")
        self.pgcode = "23505"


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, *, room_owner_id=1, insert_results=None, fail_attempts=None):
        self.room_owner_id = room_owner_id
        self.insert_results = list(insert_results or [])
        self.fail_attempts = set(fail_attempts or [])
        self.executed = []
        self.insert_attempts = 0
        self.closed = False
        self._fetchone_result = None

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        self.executed.append((query, params))
        normalized = " ".join(query.split())

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if normalized == "SELECT user_id FROM chat_rooms WHERE id = %s":
            self._fetchone_result = None if self.room_owner_id is None else (self.room_owner_id,)
            return

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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

    # 日本語: fetchone に関する処理の入口です。
    # English: Entry point for logic related to fetchone.
    def fetchone(self):
        return self._fetchone_result

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: FakeConnection に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeConnection.
class FakeConnection:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False
        self.commit_calls = 0
        self.rollback_calls = 0

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self):
        return self._cursor

    # 日本語: commit に関する処理の入口です。
    # English: Entry point for logic related to commit.
    def commit(self):
        self.commit_calls += 1

    # 日本語: rollback に関する処理の入口です。
    # English: Entry point for logic related to rollback.
    def rollback(self):
        self.rollback_calls += 1

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True

    # 日本語: コンテキスト開始時に必要な準備を行います。
    # English: Prepare the object when entering the context.
    def __enter__(self):
        return self

    # 日本語: コンテキスト終了時の後片付けを行います。
    # English: Clean up when leaving the context.
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# 日本語: ChatServiceSharedTokenTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatServiceSharedTokenTestCase.
class ChatServiceSharedTokenTestCase(unittest.TestCase):
    # 日本語: test create or get shared chat token raises 404 when room missing のテスト検証を担当します。
    # English: Handle verifying test behavior for test create or get shared chat token raises 404 when room missing.
    def test_create_or_get_shared_chat_token_raises_404_when_room_missing(self):
        fake_cursor = FakeCursor(room_owner_id=None)
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ResourceNotFoundError) as exc_info:
                create_or_get_shared_chat_token("missing-room", 10)

        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertEqual(exc_info.exception.message, "該当ルームが見つかりません")
        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    # 日本語: test create or get shared chat token raises 403 when room is not owned のテスト検証を担当します。
    # English: Handle verifying test behavior for test create or get shared chat token raises 403 when room is not owned.
    def test_create_or_get_shared_chat_token_raises_403_when_room_is_not_owned(self):
        fake_cursor = FakeCursor(room_owner_id=99)
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ForbiddenOperationError) as exc_info:
                create_or_get_shared_chat_token("room-1", 10)

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.message, "他ユーザーのチャットルームは共有できません")
        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    # 日本語: test create or get shared chat token uses on conflict and reuses existing token のテスト検証を担当します。
    # English: Handle verifying test behavior for test create or get shared chat token uses on conflict and reuses existing token.
    def test_create_or_get_shared_chat_token_uses_on_conflict_and_reuses_existing_token(self):
        fake_cursor = FakeCursor(room_owner_id=3, insert_results=["existing-share-token"])
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test create or get shared chat token retries on unique token collision のテスト検証を担当します。
    # English: Handle verifying test behavior for test create or get shared chat token retries on unique token collision.
    def test_create_or_get_shared_chat_token_retries_on_unique_token_collision(self):
        fake_cursor = FakeCursor(
            room_owner_id=5,
            insert_results=["fresh-token"],
            fail_attempts={1},
        )
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
