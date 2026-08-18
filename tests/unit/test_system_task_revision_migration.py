import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "alembic"
    / "versions"
    / "20260818_01_version_system_tasks.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("system_task_revision_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load system-task revision migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SystemTaskRevisionMigrationTestCase(unittest.TestCase):
    def test_migration_follows_current_head(self):
        module = _load_migration_module()

        self.assertEqual(module.revision, "20260818_01")
        self.assertEqual(module.down_revision, "20260809_01")

    def test_upgrade_advances_only_shared_system_tasks(self):
        module = _load_migration_module()

        with patch.object(module.op, "add_column") as add_column, patch.object(
            module.op, "execute"
        ) as execute:
            module.upgrade()

        column = add_column.call_args.args[1]
        self.assertEqual(column.name, "system_task_revision")
        self.assertFalse(column.nullable)
        sql = " ".join(execute.call_args.args[0].split())
        self.assertIn("SET system_task_revision = 2", sql)
        self.assertIn("WHERE user_id IS NULL", sql)
        self.assertIn("AND system_task_key IS NOT NULL", sql)
        self.assertNotIn("user_id IS NOT NULL", sql)

    def test_downgrade_drops_revision_column(self):
        module = _load_migration_module()

        with patch.object(module.op, "drop_column") as drop_column:
            module.downgrade()

        drop_column.assert_called_once_with("task_with_examples", "system_task_revision")


if __name__ == "__main__":
    unittest.main()
