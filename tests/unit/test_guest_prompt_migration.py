import unittest
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260824_01_add_guest_prompt_submissions.py"
)


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
