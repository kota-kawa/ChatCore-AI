import unittest
from unittest.mock import patch

from blueprints.chat.tasks import _delete_task_for_user
from blueprints.prompt_share.prompt_manage_api import (
    _delete_prompt_for_user,
    _delete_saved_prompt_for_user,
)
from blueprints.prompt_share.prompt_share_api import _remove_bookmark_for_user


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, *, rowcount=1):
        self.rowcount = rowcount
        self.executed = []
        self.closed = False

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))

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
        self.committed = False
        self.closed = False

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # 日本語: commit に関する処理の入口です。
    # English: Entry point for logic related to commit.
    def commit(self):
        self.committed = True

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


# 日本語: SoftDeleteQueryTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to SoftDeleteQueryTestCase.
class SoftDeleteQueryTestCase(unittest.TestCase):
    # 日本語: test delete task marks row deleted instead of hard deleting のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete task marks row deleted instead of hard deleting.
    def test_delete_task_marks_row_deleted_instead_of_hard_deleting(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.tasks.get_db_connection", return_value=fake_conn):
            _delete_task_for_user(5, "Task A")

        query, params = fake_cursor.executed[0]
        self.assertIn("UPDATE task_with_examples SET deleted_at = CURRENT_TIMESTAMP", query)
        self.assertNotIn("DELETE FROM task_with_examples", query)
        self.assertEqual(params, ("Task A", 5))
        self.assertTrue(fake_conn.committed)

    # 日本語: test delete saved prompt marks task row deleted のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete saved prompt marks task row deleted.
    def test_delete_saved_prompt_marks_task_row_deleted(self):
        fake_cursor = FakeCursor(rowcount=1)
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.prompt_share.prompt_manage_api.get_db_connection", return_value=fake_conn):
            deleted = _delete_saved_prompt_for_user(8, 99)

        query, params = fake_cursor.executed[0]
        self.assertEqual(deleted, 1)
        self.assertIn("UPDATE task_with_examples SET deleted_at = CURRENT_TIMESTAMP", query)
        self.assertEqual(params, (99, 8))

    # 日本語: test delete prompt marks prompt row deleted のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete prompt marks prompt row deleted.
    def test_delete_prompt_marks_prompt_row_deleted(self):
        fake_cursor = FakeCursor(rowcount=1)
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.prompt_share.prompt_manage_api.get_db_connection", return_value=fake_conn):
            deleted = _delete_prompt_for_user(8, 77)

        query, params = fake_cursor.executed[0]
        self.assertEqual(deleted, 1)
        self.assertIn("UPDATE prompts SET deleted_at = CURRENT_TIMESTAMP", query)
        self.assertNotIn("DELETE FROM prompts", query)
        self.assertEqual(params, (77, 8))

    # 日本語: test remove bookmark deletes prompt list entry のテスト検証を担当します。
    # English: Handle verifying test behavior for test remove bookmark deletes prompt list entry.
    def test_remove_bookmark_deletes_prompt_list_entry(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.prompt_share.prompt_share_api.get_db_connection", return_value=fake_conn):
            _remove_bookmark_for_user(3, 42)

        query, params = fake_cursor.executed[0]
        self.assertIn("DELETE FROM prompt_list_entries", query)
        self.assertEqual(params, (3, 42))


if __name__ == "__main__":
    unittest.main()
