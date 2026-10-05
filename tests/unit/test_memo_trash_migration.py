import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

MIGRATION_PATH = Path(__file__).parents[2] / "alembic" / "versions" / "20261005_01_add_memo_trash.py"

spec = importlib.util.spec_from_file_location("memo_trash_migration", MIGRATION_PATH)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the memo trash migration module.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def _connection(trashed: int) -> MagicMock:
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = trashed
    return connection


class MemoTrashMigrationTestCase(unittest.TestCase):
    def setUp(self):
        self.source = MIGRATION_PATH.read_text(encoding="utf-8")
        self.upgrade = self.source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

    def test_revision_follows_context_fact_confirmation(self):
        self.assertEqual(migration.revision, "20261005_01")
        self.assertEqual(migration.down_revision, "20260930_01")

    def test_upgrade_adds_only_a_nullable_column_and_a_partial_concurrent_index(self):
        self.assertIn("ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP", self.upgrade)
        self.assertNotIn("NOT NULL\n", self.upgrade.split("ADD COLUMN", 1)[1].split('"""', 1)[0])
        self.assertIn("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memo_entries_deleted_at", self.upgrade)
        self.assertIn("WHERE deleted_at IS NOT NULL", self.upgrade)
        self.assertNotIn("UPDATE ", self.upgrade)
        self.assertNotIn("DELETE ", self.upgrade)

    def test_downgrade_is_refused_while_trashed_memos_exist(self):
        connection = _connection(trashed=3)
        with patch.object(migration.op, "get_bind", return_value=connection), patch.object(
            migration.op, "execute"
        ) as execute:
            with self.assertRaisesRegex(RuntimeError, "3 trashed memo"):
                migration.downgrade()

        execute.assert_not_called()

    def test_downgrade_drops_the_column_when_the_trash_is_empty(self):
        connection = _connection(trashed=0)
        with patch.object(migration.op, "get_bind", return_value=connection), patch.object(
            migration.op, "execute"
        ) as execute:
            migration.downgrade()

        statements = [" ".join(str(call.args[0]).split()) for call in connection.execute.call_args_list]
        self.assertTrue(statements[0].startswith("LOCK TABLE memo_entries"))
        self.assertIn("deleted_at IS NOT NULL", statements[1])
        execute.assert_called_once_with("ALTER TABLE memo_entries DROP COLUMN IF EXISTS deleted_at")


if __name__ == "__main__":
    unittest.main()
