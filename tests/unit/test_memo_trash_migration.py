import unittest
from pathlib import Path

MIGRATION_PATH = Path(__file__).parents[2] / "alembic" / "versions" / "20261005_01_add_memo_trash.py"


class MemoTrashMigrationTestCase(unittest.TestCase):
    def setUp(self):
        self.source = MIGRATION_PATH.read_text(encoding="utf-8")
        self.upgrade = self.source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        self.downgrade = self.source.split("def downgrade()", 1)[1]

    def test_revision_follows_context_fact_confirmation(self):
        self.assertIn('revision: str = "20261005_01"', self.source)
        self.assertIn('= "20260930_01"', self.source)

    def test_upgrade_adds_only_a_nullable_column_and_a_partial_concurrent_index(self):
        self.assertIn("ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP", self.upgrade)
        self.assertNotIn("NOT NULL\n", self.upgrade.split("ADD COLUMN", 1)[1].split('"""', 1)[0])
        self.assertIn("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memo_entries_deleted_at", self.upgrade)
        self.assertIn("WHERE deleted_at IS NOT NULL", self.upgrade)
        self.assertNotIn("UPDATE ", self.upgrade)
        self.assertNotIn("DELETE ", self.upgrade)

    def test_downgrade_drops_the_index_before_the_column(self):
        self.assertLess(
            self.downgrade.index("DROP INDEX CONCURRENTLY IF EXISTS idx_memo_entries_deleted_at"),
            self.downgrade.index("DROP COLUMN IF EXISTS deleted_at"),
        )


if __name__ == "__main__":
    unittest.main()
