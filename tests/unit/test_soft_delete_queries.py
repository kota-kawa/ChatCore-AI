import unittest
from unittest.mock import patch

from blueprints.chat.tasks import _delete_task_for_user
from blueprints.prompt_share.prompt_manage_api import (
    _delete_prompt_for_user,
    _delete_saved_prompt_for_user,
)
from blueprints.prompt_share.prompt_share_api import _remove_bookmark_for_user


# テスト用の疑似DBカーソルクラス。
# Mock database cursor class for testing.
class FakeCursor:
    # インスタンス生成時に必要な初期状態を設定します。
    # Initialize the required instance state when the object is created.
    def __init__(self, *, rowcount=1):
        self.rowcount = rowcount
        self.executed = []
        self.closed = False

    # クエリを実行し、実行されたクエリとパラメータを記録します。
    # Execute a query and record the query string and params.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))

    # カーソルを閉じます。
    # Close the cursor.
    def close(self):
        self.closed = True


# テスト用の疑似DBコネクションクラス。
# Mock database connection class for testing.
class FakeConnection:
    # インスタンス生成時に必要な初期状態を設定します。
    # Initialize the required instance state when the object is created.
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.closed = False

    # カーソルを返却します。
    # Return the cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # コミットされたことを記録します。
    # Commit the current mock transaction.
    def commit(self):
        self.committed = True

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


# 物理削除(Hard Delete)ではなく論理削除(Soft Delete)が行われているかを検証するテストクラス。
# Test class to verify that soft deletes are performed instead of hard deletes.
class SoftDeleteQueryTestCase(unittest.TestCase):
    # タスクの削除処理において、DELETE文ではなくUPDATE文でdeleted_atカラムを更新することを確認します。
    # Verify that deleting a task updates the deleted_at column using UPDATE instead of DELETE.
    def test_delete_task_marks_row_deleted_instead_of_hard_deleting(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        # タスク削除関数をモックされたDB接続を利用して呼び出し
        # Call the delete task function using the mocked DB connection
        with patch("blueprints.chat.tasks.get_db_connection", return_value=fake_conn):
            _delete_task_for_user(5, "Task A")

        query, params = fake_cursor.executed[0]
        self.assertIn("UPDATE task_with_examples SET deleted_at = CURRENT_TIMESTAMP", query)
        self.assertNotIn("DELETE FROM task_with_examples", query)
        self.assertEqual(params, ("Task A", 5))
        self.assertTrue(fake_conn.committed)

    # 保存されたプロンプト（タスク）の削除処理において、UPDATE文でdeleted_atが更新されることを確認します。
    # Verify that deleting a saved prompt updates the deleted_at column of the task using UPDATE.
    def test_delete_saved_prompt_marks_task_row_deleted(self):
        fake_cursor = FakeCursor(rowcount=1)
        fake_conn = FakeConnection(fake_cursor)

        # 保存プロンプト削除関数をモックされたDB接続を利用して呼び出し
        # Call the delete saved prompt function using the mocked DB connection
        with patch("blueprints.prompt_share.prompt_manage_api.get_db_connection", return_value=fake_conn):
            deleted = _delete_saved_prompt_for_user(8, 99)

        query, params = fake_cursor.executed[0]
        self.assertEqual(deleted, 1)
        self.assertIn("UPDATE task_with_examples SET deleted_at = CURRENT_TIMESTAMP", query)
        self.assertEqual(params, (99, 8))

    # 共有プロンプトの削除処理において、DELETE文ではなくUPDATE文でdeleted_atが更新されることを確認します。
    # Verify that deleting a shared prompt updates the deleted_at column of the prompt using UPDATE instead of DELETE.
    def test_delete_prompt_marks_prompt_row_deleted(self):
        fake_cursor = FakeCursor(rowcount=1)
        fake_conn = FakeConnection(fake_cursor)

        # プロンプト削除関数をモックされたDB接続を利用して呼び出し
        # Call the delete prompt function using the mocked DB connection
        with patch("blueprints.prompt_share.prompt_manage_api.get_db_connection", return_value=fake_conn):
            deleted = _delete_prompt_for_user(8, 77)

        query, params = fake_cursor.executed[0]
        self.assertEqual(deleted, 1)
        self.assertIn("UPDATE prompts SET deleted_at = CURRENT_TIMESTAMP", query)
        self.assertNotIn("DELETE FROM prompts", query)
        self.assertEqual(params, (77, 8))

    # ブックマークの削除（解除）処理においては、論理削除ではなく物理的な削除（DELETE文）が行われることを確認します。
    # Verify that removing a bookmark executes a hard delete (DELETE statement) in prompt_list_entries.
    def test_remove_bookmark_deletes_prompt_list_entry(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        # ブックマーク削除関数をモックされたDB接続を利用して呼び出し
        # Call the remove bookmark function using the mocked DB connection
        with patch("blueprints.prompt_share.prompt_share_api.get_db_connection", return_value=fake_conn):
            _remove_bookmark_for_user(3, 42)

        query, params = fake_cursor.executed[0]
        self.assertIn("DELETE FROM prompt_list_entries", query)
        self.assertEqual(params, (3, 42))


if __name__ == "__main__":
    unittest.main()
