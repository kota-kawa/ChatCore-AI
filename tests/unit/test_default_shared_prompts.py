import unittest
from unittest.mock import patch

from services.default_shared_prompts import (
    DEFAULT_SHARED_PROMPTS,
    ensure_default_shared_prompts,
)
from tests.helpers.db_helpers import TransactionTrackingConnection


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, *, owner_id=None, existing_prompt_titles=None):
        self.owner_id = owner_id
        self.existing_prompt_titles = set(existing_prompt_titles or [])
        self.inserted_prompts = []
        self.executed_queries = []
        self._fetchone_result = None
        self._fetchall_result = None
        self.closed = False

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed_queries.append((normalized, params))

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "SELECT id FROM users WHERE email = %s" in normalized:
            self._fetchone_result = (self.owner_id,) if self.owner_id is not None else None
            return

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "INSERT INTO users" in normalized and "RETURNING id" in normalized:
            self.owner_id = 999
            self._fetchone_result = (self.owner_id,)
            return

        if "SELECT title FROM prompts" in normalized and "title IN" in normalized:
            titles = params[1:]
            self._fetchall_result = [(title,) for title in titles if title in self.existing_prompt_titles]
            return

        if "INSERT INTO prompts" in normalized:
            title = params[1]
            self.inserted_prompts.append(title)
            self.existing_prompt_titles.add(title)
            self._fetchone_result = None
            return

        self._fetchone_result = None

    # 日本語: fetchone に関する処理の入口です。
    # English: Entry point for logic related to fetchone.
    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
        return result

    # 日本語: fetchall に関する処理の入口です。
    # English: Entry point for logic related to fetchall.
    def fetchall(self):
        result = self._fetchall_result or []
        self._fetchall_result = None
        return result

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: DefaultSharedPromptsTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to DefaultSharedPromptsTestCase.
class DefaultSharedPromptsTestCase(unittest.TestCase):
    # 日本語: test inserts samples when they are missing のテスト検証を担当します。
    # English: Handle verifying test behavior for test inserts samples when they are missing.
    def test_inserts_samples_when_they_are_missing(self):
        fake_cursor = FakeCursor()
        fake_conn = TransactionTrackingConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.default_shared_prompts.get_db_connection", return_value=fake_conn):
            inserted = ensure_default_shared_prompts()

        self.assertEqual(inserted, len(DEFAULT_SHARED_PROMPTS))
        self.assertTrue(fake_conn.committed)
        self.assertFalse(fake_conn.rolled_back)
        self.assertTrue(fake_conn.closed)
        self.assertTrue(fake_cursor.closed)
        self.assertEqual(len(fake_cursor.inserted_prompts), len(DEFAULT_SHARED_PROMPTS))
        self.assertIsNotNone(fake_cursor.owner_id)
        self.assertEqual(
            len([query for query, _ in fake_cursor.executed_queries if "SELECT title FROM prompts" in query]),
            1,
        )

    # 日本語: test skips when all samples already exist のテスト検証を担当します。
    # English: Handle verifying test behavior for test skips when all samples already exist.
    def test_skips_when_all_samples_already_exist(self):
        existing_titles = {prompt["title"] for prompt in DEFAULT_SHARED_PROMPTS}
        fake_cursor = FakeCursor(owner_id=999, existing_prompt_titles=existing_titles)
        fake_conn = TransactionTrackingConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.default_shared_prompts.get_db_connection", return_value=fake_conn):
            inserted = ensure_default_shared_prompts()

        self.assertEqual(inserted, 0)
        self.assertFalse(fake_conn.committed)
        self.assertFalse(fake_conn.rolled_back)
        self.assertTrue(fake_conn.closed)
        self.assertTrue(fake_cursor.closed)
        self.assertEqual(fake_cursor.inserted_prompts, [])
        self.assertFalse(
            any("INSERT INTO users" in query for query, _ in fake_cursor.executed_queries)
        )
        self.assertEqual(
            len([query for query, _ in fake_cursor.executed_queries if "SELECT title FROM prompts" in query]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
