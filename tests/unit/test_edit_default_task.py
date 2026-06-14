import asyncio
import unittest
from unittest.mock import patch

from blueprints.chat.tasks import edit_task
from tests.helpers.request_helpers import build_request


# 日本語: テスト用の擬似Fake Cursorクラスです。
# English: Mock Fake Cursor class for testing.
class FakeCursor:
    def __init__(self):
        self.executed = []
        self._fetchone_result = None

    def execute(self, query, params=None):
        self.executed.append((query, params))
        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if "SELECT 1" in query:
            self._fetchone_result = (1,)
        else:
            self._fetchone_result = None

    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
        return result

    # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
    def close(self):
        pass


# 日本語: テスト用の擬似Fake Connectionクラスです。
# English: Mock Fake Connection class for testing.
class FakeConnection:
    def __init__(self):
        self.committed = False
        self.closed = False
        self.cursors = []

    # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
    def cursor(self, dictionary=False):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.committed = True

    # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
    def close(self):
        self.closed = True


def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/edit_task",
        json_body=json_body,
        session=session,
    )


# 日本語: Edit Default Taskの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Edit Default Task.
class EditDefaultTaskTestCase(unittest.TestCase):
    # 日本語: editingcopiedデフォルトタスクがallowedことを検証します。
    # English: Verify that editing copied default task is allowed.
    def test_editing_copied_default_task_is_allowed(self):
        fake_connection = FakeConnection()
        request = make_request(
            {
                "old_task": "Default Task",
                "new_task": "Updated Task",
                "prompt_template": "Prompt",
                "response_rules": "Rules",
                "output_skeleton": "Skeleton",
                "input_examples": "input",
                "output_examples": "output",
            },
            session={"user_id": 123},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.tasks.get_db_connection", return_value=fake_connection):
            response = asyncio.run(edit_task(request))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(fake_connection.committed)
        self.assertTrue(any("SELECT 1" in query for query, _ in fake_connection.cursors[0].executed))


if __name__ == "__main__":
    unittest.main()
