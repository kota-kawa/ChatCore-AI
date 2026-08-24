import unittest
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260824_02_add_prompt_view_counts.py"
)


class PromptViewCountMigrationTestCase(unittest.TestCase):
    def test_migration_creates_separate_non_negative_counter_and_popularity_index(self):
        sql = MIGRATION_PATH.read_text()

        self.assertIn('revision: str = "20260824_02"', sql)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "20260824_01"', sql)
        self.assertIn("CREATE TABLE prompt_view_counts", sql)
        self.assertIn("view_count BIGINT NOT NULL DEFAULT 0", sql)
        self.assertIn("CHECK (view_count >= 0)", sql)
        self.assertIn("REFERENCES prompts(id) ON DELETE CASCADE", sql)
        self.assertIn("ON prompt_view_counts (view_count DESC, prompt_id DESC)", sql)
        self.assertIn("DROP TABLE prompt_view_counts", sql)


if __name__ == "__main__":
    unittest.main()
