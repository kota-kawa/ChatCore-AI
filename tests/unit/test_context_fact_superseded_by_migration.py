"""alembic マイグレーション 20261120_05（context_facts に superseded_by_fact_id を追加）の連鎖と SQL、モデルとの一致を検証するテスト。

Tests the revision chain and SQL of alembic migration 20261120_05, which adds superseded_by_fact_id to
context_facts, and its agreement with the model.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex

from services.models import ContextFact

migration_path = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261120_05_add_context_fact_superseded_by.py"
)
spec = importlib.util.spec_from_file_location("context_fact_superseded_by_migration", migration_path)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the context fact superseded_by migration.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


# 日本語: op.execute に渡された SQL を、空白を 1 つに揃えた文字列のリストにします。
# English: Return the SQL passed to op.execute with whitespace collapsed to single spaces.
def _statements(execute):
    return [" ".join(call.args[0].split()) for call in execute.call_args_list]


def _run_upgrade():
    # 日本語: 実行順（ロック待ちの上限→ALTER→索引→上限を戻す）を保つため、1 つの親モックに子モックを付けて記録します。
    # English: One parent mock records the call order (bound the lock wait, ALTER, index, reset the bound).
    recorder = MagicMock()
    with (
        patch.object(migration.op, "execute", recorder.execute),
        patch.object(migration.op, "create_index", recorder.create_index),
    ):
        migration.upgrade()
    return recorder


class ContextFactSupersededByMigrationTestCase(unittest.TestCase):
    def test_revision_follows_the_memory_use_setting_migration(self):
        self.assertEqual(migration.revision, "20261120_05")
        self.assertEqual(migration.down_revision, "20261120_04")

    def test_upgrade_adds_a_nullable_self_reference_that_clears_on_delete(self):
        recorder = _run_upgrade()

        [bound, alter, reset] = _statements(recorder.execute)
        self.assertEqual(bound, "SET LOCAL lock_timeout = '5s'")
        self.assertEqual(reset, "SET LOCAL lock_timeout TO DEFAULT")
        self.assertIn("ADD COLUMN superseded_by_fact_id INTEGER,", alter)
        self.assertNotIn("NOT NULL", alter)
        self.assertNotIn("DEFAULT", alter)
        self.assertIn(
            "FOREIGN KEY (superseded_by_fact_id) REFERENCES context_facts (id) ON DELETE SET NULL",
            alter,
        )

    def test_upgrade_builds_the_partial_child_index_between_the_lock_bound_and_its_reset(self):
        recorder = _run_upgrade()

        names = [call[0] for call in recorder.mock_calls]
        self.assertEqual(names, ["execute", "execute", "create_index", "execute"])
        index_call = recorder.create_index.call_args
        self.assertEqual(index_call.args, ("idx_context_facts_superseded_by", "context_facts", ["superseded_by_fact_id"]))
        self.assertEqual(str(index_call.kwargs["postgresql_where"]), "superseded_by_fact_id IS NOT NULL")
        self.assertTrue(index_call.kwargs["if_not_exists"])

    def test_upgrade_does_not_touch_existing_rows(self):
        recorder = _run_upgrade()

        self.assertFalse(any("UPDATE" in sql for sql in _statements(recorder.execute)))

    def test_downgrade_drops_the_index_constraint_and_column(self):
        with patch.object(migration.op, "execute") as execute, patch.object(migration.op, "drop_index") as drop_index:
            migration.downgrade()

        drop_index.assert_called_once_with("idx_context_facts_superseded_by", table_name="context_facts", if_exists=True)
        (statement,) = _statements(execute)
        self.assertIn("DROP CONSTRAINT IF EXISTS fk_context_facts_superseded_by", statement)
        self.assertIn("DROP COLUMN IF EXISTS superseded_by_fact_id", statement)

    def test_model_matches_the_migration(self):
        table = ContextFact.__table__
        column = table.c.superseded_by_fact_id
        self.assertTrue(column.nullable)
        self.assertIsNone(column.server_default)
        [foreign_key] = column.foreign_keys
        self.assertEqual(foreign_key.target_fullname, "context_facts.id")
        self.assertEqual(foreign_key.ondelete, "SET NULL")
        self.assertEqual(foreign_key.constraint.name, "fk_context_facts_superseded_by")
        index = next(index for index in table.indexes if index.name == "idx_context_facts_superseded_by")
        self.assertEqual([item.name for item in index.columns], ["superseded_by_fact_id"])
        self.assertIn(
            "WHERE superseded_by_fact_id IS NOT NULL",
            " ".join(str(CreateIndex(index).compile(dialect=dialect())).split()),
        )

    def test_the_reason_the_column_goes_with_is_already_allowed_by_the_check(self):
        check = next(
            constraint
            for constraint in ContextFact.__table__.constraints
            if constraint.name == "ck_context_facts_deprecated_reason"
        )
        self.assertIn("'superseded'", str(check.sqltext))


if __name__ == "__main__":
    unittest.main()
