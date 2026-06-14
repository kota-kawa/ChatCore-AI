import unittest
from unittest.mock import patch

from services.default_tasks import (
    default_task_payloads,
    default_task_rows,
    ensure_default_tasks_seeded,
    load_default_tasks,
)
from tests.helpers.db_helpers import TransactionTrackingConnection


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, *, existing_names=None):
        self.existing_names = set(existing_names or [])
        self.inserted_names = []
        self.executed_queries = []
        self._fetchall_result = []
        self.closed = False

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed_queries.append((normalized, params))

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "SELECT name FROM task_with_examples WHERE user_id IS NULL" in normalized:
            self._fetchall_result = [(name,) for name in sorted(self.existing_names)]
            return

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "INSERT INTO task_with_examples" in normalized:
            name = params[0]
            self.inserted_names.append(name)
            self.existing_names.add(name)

    # 日本語: fetchall に関する処理の入口です。
    # English: Entry point for logic related to fetchall.
    def fetchall(self):
        result = self._fetchall_result
        self._fetchall_result = []
        return result

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


SAMPLE_TASKS = [
    {
        "name": "Task A",
        "prompt_template": "Prompt A",
        "response_rules": "Rules A",
        "output_skeleton": "Skeleton A",
        "input_examples": "Input A",
        "output_examples": "Output A",
        "display_order": 0,
    },
    {
        "name": "Task B",
        "prompt_template": "Prompt B",
        "response_rules": "Rules B",
        "output_skeleton": "Skeleton B",
        "input_examples": "Input B",
        "output_examples": "Output B",
        "display_order": 1,
    },
]


# 日本語: DefaultTasksTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to DefaultTasksTestCase.
class DefaultTasksTestCase(unittest.TestCase):
    # 日本語: test payloads and rows are derived from shared data のテスト検証を担当します。
    # English: Handle verifying test behavior for test payloads and rows are derived from shared data.
    def test_payloads_and_rows_are_derived_from_shared_data(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.default_tasks.load_default_tasks", return_value=SAMPLE_TASKS):
            payloads = default_task_payloads()
            rows = default_task_rows()

        self.assertEqual(len(payloads), 2)
        self.assertTrue(all(payload["is_default"] for payload in payloads))
        self.assertEqual(payloads[0]["name"], "Task A")
        self.assertEqual(payloads[0]["response_rules"], "Rules A")
        self.assertEqual(payloads[0]["output_skeleton"], "Skeleton A")
        self.assertEqual(
            rows[0],
            ("Task A", "Prompt A", "Rules A", "Skeleton A", "Input A", "Output A", 0),
        )

    # 日本語: test seed inserts missing default tasks のテスト検証を担当します。
    # English: Handle verifying test behavior for test seed inserts missing default tasks.
    def test_seed_inserts_missing_default_tasks(self):
        fake_cursor = FakeCursor(existing_names=[])
        fake_conn = TransactionTrackingConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.default_tasks.get_db_connection", return_value=fake_conn), patch(
            "services.default_tasks.load_default_tasks", return_value=SAMPLE_TASKS
        ):
            inserted = ensure_default_tasks_seeded()

        self.assertEqual(inserted, len(SAMPLE_TASKS))
        self.assertEqual(fake_cursor.inserted_names, ["Task A", "Task B"])
        self.assertTrue(fake_conn.committed)
        self.assertFalse(fake_conn.rolled_back)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)

    # 日本語: test seed skips when default tasks already exist のテスト検証を担当します。
    # English: Handle verifying test behavior for test seed skips when default tasks already exist.
    def test_seed_skips_when_default_tasks_already_exist(self):
        existing_names = {task["name"] for task in SAMPLE_TASKS}
        fake_cursor = FakeCursor(existing_names=existing_names)
        fake_conn = TransactionTrackingConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.default_tasks.get_db_connection", return_value=fake_conn), patch(
            "services.default_tasks.load_default_tasks", return_value=SAMPLE_TASKS
        ):
            inserted = ensure_default_tasks_seeded()

        self.assertEqual(inserted, 0)
        self.assertEqual(fake_cursor.inserted_names, [])
        self.assertFalse(fake_conn.committed)
        self.assertFalse(fake_conn.rolled_back)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)

    # 日本語: test repository default tasks include full seed set のテスト検証を担当します。
    # English: Handle verifying test behavior for test repository default tasks include full seed set.
    def test_repository_default_tasks_include_full_seed_set(self):
        expected_names = {
            "📧 メール作成",
            "💡 アイデア発想",
            "📄 要約",
            "🛠️ 問題解決",
            "📋 問題へ回答",
            "ℹ️ 情報提供",
            "🌐 翻訳",
            "🔄 比較・検討",
            "✏️ 文章の添削・校正",
            "✈️ 旅行計画",
            "💬 悩み相談",
            "📨 メッセージへの返答",
            "📝 文章作成",
            "📊 議事録・メモ整理",
        }

        load_default_tasks.cache_clear()
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            tasks = load_default_tasks()
        finally:
            load_default_tasks.cache_clear()

        task_names = {task["name"] for task in tasks}
        self.assertEqual(len(tasks), len(expected_names))
        self.assertSetEqual(task_names, expected_names)

    # 日本語: test repository email task uses code block for ready to send body のテスト検証を担当します。
    # English: Handle verifying test behavior for test repository email task uses code block for ready to send body.
    def test_repository_email_task_uses_code_block_for_ready_to_send_body(self):
        load_default_tasks.cache_clear()
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            tasks = load_default_tasks()
        finally:
            load_default_tasks.cache_clear()

        email_task = next(task for task in tasks if task["name"] == "📧 メール作成")
        self.assertIn("コードブロック", email_task["prompt_template"])
        self.assertIn("コードブロック", email_task["response_rules"])
        self.assertIn("```text", email_task["output_skeleton"])
        self.assertIn("新機能説明会", email_task["input_examples"])
        self.assertIn("```text", email_task["output_examples"])

    # 日本語: test repository reply task uses code blocks for ready to send replies のテスト検証を担当します。
    # English: Handle verifying test behavior for test repository reply task uses code blocks for ready to send replies.
    def test_repository_reply_task_uses_code_blocks_for_ready_to_send_replies(self):
        load_default_tasks.cache_clear()
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            tasks = load_default_tasks()
        finally:
            load_default_tasks.cache_clear()

        reply_task = next(task for task in tasks if task["name"] == "📨 メッセージへの返答")
        self.assertIn("コードブロック", reply_task["prompt_template"])
        self.assertIn("コードブロック", reply_task["response_rules"])
        self.assertIn("```text", reply_task["output_skeleton"])

    # 日本語: test repository table or format sensitive tasks include examples のテスト検証を担当します。
    # English: Handle verifying test behavior for test repository table or format sensitive tasks include examples.
    def test_repository_table_or_format_sensitive_tasks_include_examples(self):
        load_default_tasks.cache_clear()
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            tasks = load_default_tasks()
        finally:
            load_default_tasks.cache_clear()

        comparison_task = next(task for task in tasks if task["name"] == "🔄 比較・検討")
        meeting_task = next(task for task in tasks if task["name"] == "📊 議事録・メモ整理")

        self.assertTrue(comparison_task["input_examples"])
        self.assertIn("| 観点 |", comparison_task["output_examples"])
        self.assertTrue(meeting_task["input_examples"])
        self.assertIn("| 担当 | 内容 | 期限 |", meeting_task["output_examples"])

    # 日本語: test repository problem solving task requests concise rationale only のテスト検証を担当します。
    # English: Handle verifying test behavior for test repository problem solving task requests concise rationale only.
    def test_repository_problem_solving_task_requests_concise_rationale_only(self):
        load_default_tasks.cache_clear()
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            tasks = load_default_tasks()
        finally:
            load_default_tasks.cache_clear()

        answer_task = next(task for task in tasks if task["name"] == "📋 問題へ回答")
        self.assertIn("簡潔", answer_task["prompt_template"])
        self.assertIn("必要な範囲", answer_task["response_rules"])
        self.assertIn("根拠・手順", answer_task["output_skeleton"])
        self.assertNotIn("途中の考え方", answer_task["prompt_template"])


if __name__ == "__main__":
    unittest.main()
