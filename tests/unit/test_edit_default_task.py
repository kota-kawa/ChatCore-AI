import asyncio
import unittest
from unittest.mock import patch

from blueprints.chat.tasks import edit_task
from tests.helpers.request_helpers import build_request


# 日本語: テスト用のフェイクDBカーソルクラス。実行されたクエリを記録し、SELECT 1 に対してのみ結果を返します。
# English: Fake DB cursor for testing. Logs executed queries and returns a result only for SELECT 1.
class FakeCursor:
    # 日本語: 実行済みクエリリストとフェッチ結果バッファを初期化します。
    # English: Initialize the executed query list and fetch result buffer.
    def __init__(self):
        self.executed = []
        self._fetchone_result = None

    # 日本語: クエリと引数を記録し、SELECT 1 クエリの場合はフェッチ結果として (1,) をセットします。
    # English: Record the query and params. Set (1,) as fetchone result if query contains SELECT 1.
    def execute(self, query, params=None):
        self.executed.append((query, params))
        if "SELECT 1" in query:
            self._fetchone_result = (1,)
        else:
            self._fetchone_result = None

    # 日本語: バッファ内のフェッチ結果を1度だけ返し、次回以降はNoneを返します。
    # English: Return the buffered fetchone result once, then reset to None.
    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
        return result

    # 日本語: カーソルをクローズします（このフェイクでは何もしません）。
    # English: Close the cursor (no-op for this fake).
    def close(self):
        pass


# 日本語: テスト用のフェイクDBコネクションクラス。コミット・クローズ状態を追跡します。
# English: Fake DB connection for testing. Tracks commit and close states.
class FakeConnection:
    # 日本語: コミット・クローズフラグとカーソルリストを初期化します。
    # English: Initialize commit, close flags, and cursor list.
    def __init__(self):
        self.committed = False
        self.closed = False
        self.cursors = []

    # 日本語: 新しいフェイクカーソルを生成して返します。
    # English: Create and return a new fake cursor.
    def cursor(self, dictionary=False):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor

    # 日本語: コミット済みフラグを立てます。
    # English: Mark the connection as committed.
    def commit(self):
        self.committed = True

    # 日本語: クローズ済みフラグを立てます。
    # English: Mark the connection as closed.
    def close(self):
        self.closed = True


# 日本語: テスト用のPOSTリクエストを構築するヘルパー関数。
# English: Helper function to build a POST request for testing.
def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/edit_task",
        json_body=json_body,
        session=session,
    )


# 日本語: デフォルトタスクの編集APIエンドポイントをテストするクラス。
# English: Test class for the default task edit API endpoint.
class EditDefaultTaskTestCase(unittest.TestCase):
    # 日本語: コピーされたデフォルトタスクの編集が正常に行われ、DBへのコミットが実行されることを検証します。
    # English: Verify that editing a copied default task succeeds and commits to the database.
    def test_editing_copied_default_task_is_allowed(self):
        fake_connection = FakeConnection()
        # 日本語: タスク更新に必要な全フィールドを含むPOSTリクエストを構築
        # English: Build a POST request with all fields required for task update
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

        # 日本語: DB接続をフェイク接続に差し替えてタスク編集エンドポイントを呼び出す
        # English: Swap the DB connection with the fake and call the task edit endpoint
        with patch("blueprints.chat.tasks.get_db_connection", return_value=fake_connection):
            response = asyncio.run(edit_task(request))

        # 日本語: 200レスポンス、DBコミット、SELECT 1による存在チェックが行われたことを確認
        # English: Confirm 200 response, DB commit, and that SELECT 1 existence check was performed
        self.assertEqual(response.status_code, 200)
        self.assertTrue(fake_connection.committed)
        self.assertTrue(any("SELECT 1" in query for query, _ in fake_connection.cursors[0].executed))


if __name__ == "__main__":
    unittest.main()
