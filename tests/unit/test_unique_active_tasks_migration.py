import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260730_01_enforce_unique_active_tasks.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("unique_active_tasks_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load unique active tasks migration")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


class UniqueActiveTasksMigrationTestCase(unittest.TestCase):
    def test_upgrade_cleans_data_before_adding_partial_unique_indexes(self):
        migration = load_migration()

        with patch.object(migration.op, "add_column") as add_column, patch.object(
            migration.op, "execute"
        ) as execute:
            migration.upgrade()

        self.assertEqual(migration.down_revision, "20260728_02")
        self.assertEqual(add_column.call_args.args[0], "task_with_examples")
        self.assertEqual(add_column.call_args.args[1].name, "is_system_task_customized")
        sql = "\n".join(str(call.args[0]) for call in execute.call_args_list)
        cleanup_position = sql.index("WITH duplicate_groups")
        index_position = sql.index(
            "CREATE UNIQUE INDEX uq_task_with_examples_active_user_normalized_name"
        )
        self.assertLess(cleanup_position, index_position)
        self.assertIn("SET deleted_at = CURRENT_TIMESTAMP", sql)
        self.assertIn("matched.match_count = 1", sql)
        self.assertIn("prompt.content = task.prompt_template", sql)
        self.assertIn("SET system_task_key = NULL", sql)
        self.assertIn("SET source_prompt_id = NULL", sql)
        self.assertIn("LOWER(BTRIM(name))", sql)
        self.assertIn("uq_task_with_examples_active_user_system_key", sql)
        self.assertIn("uq_task_with_examples_active_shared_system_key", sql)
        self.assertIn("uq_task_with_examples_active_user_source_prompt", sql)

    def test_downgrade_removes_indexes_and_customization_column(self):
        migration = load_migration()

        with patch.object(migration.op, "execute") as execute, patch.object(
            migration.op, "drop_column"
        ) as drop_column:
            migration.downgrade()

        sql = "\n".join(str(call.args[0]) for call in execute.call_args_list)
        self.assertIn("uq_task_with_examples_active_user_normalized_name", sql)
        self.assertIn("uq_task_with_examples_active_user_source_prompt", sql)
        drop_column.assert_called_once_with(
            "task_with_examples",
            "is_system_task_customized",
        )


if __name__ == "__main__":
    unittest.main()
