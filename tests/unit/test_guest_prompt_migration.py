"""ゲスト投稿用 Alembic migration（guest_prompt_submissions の追加と prompts.user_id の NULL 許可）の SQL を静的に検証するテスト。

Static tests of the guest prompt Alembic migration (guest_prompt_submissions table and nullable prompts.user_id).
"""

import unittest
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260824_01_add_guest_prompt_submissions.py"
)


# migration ファイルの SQL 文字列を読み、ゲスト所有とハッシュ化された識別子の索引が含まれることを確かめる。
# Reads the migration SQL and checks it allows guest ownership and indexes the hashed identifiers.
class GuestPromptMigrationTestCase(unittest.TestCase):
    def test_migration_allows_guest_owner_and_indexes_hashed_identifiers(self):
        sql = MIGRATION_PATH.read_text()

        self.assertIn("ALTER TABLE prompts ALTER COLUMN user_id DROP NOT NULL", sql)
        self.assertIn("CREATE TABLE guest_prompt_submissions", sql)
        self.assertIn("guest_cookie_hash CHAR(64) NOT NULL", sql)
        self.assertIn("client_ip_hash CHAR(64) NOT NULL", sql)
        self.assertIn("idx_guest_prompt_submissions_cookie_created_at", sql)
        self.assertIn("idx_guest_prompt_submissions_ip_created_at", sql)
        self.assertIn("FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE", sql)


if __name__ == "__main__":
    unittest.main()
