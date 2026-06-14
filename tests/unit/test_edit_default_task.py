import asyncio
import unittest
from unittest.mock import patch

from blueprints.chat.tasks import edit_task
from tests.helpers.request_helpers import build_request


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        self.executed = []
        self._fetchone_result = None

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        self.executed.append((query, params))
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "SELECT 1" in query:
            self._fetchone_result = (1,)
        else:
            self._fetchone_result = None

    # 日本語: fetchone に関する処理の入口です。
    # English: Entry point for logic related to fetchone.
    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
        return result

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        pass


# 日本語: FakeConnection に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeConnection.
class FakeConnection:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        self.committed = False
        self.closed = False
        self.cursors = []

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self, dictionary=False):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor

    # 日本語: commit に関する処理の入口です。
    # English: Entry point for logic related to commit.
    def commit(self):
        self.committed = True

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/edit_task",
        json_body=json_body,
        session=session,
    )


# 日本語: EditDefaultTaskTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to EditDefaultTaskTestCase.
class EditDefaultTaskTestCase(unittest.TestCase):
    # 日本語: test editing copied default task is allowed のテスト検証を担当します。
    # English: Handle verifying test behavior for test editing copied default task is allowed.
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

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.tasks.get_db_connection", return_value=fake_connection):
            response = asyncio.run(edit_task(request))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(fake_connection.committed)
        self.assertTrue(any("SELECT 1" in query for query, _ in fake_connection.cursors[0].executed))


if __name__ == "__main__":
    unittest.main()
