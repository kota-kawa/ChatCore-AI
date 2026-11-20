"""alembic マイグレーション 20261120_02（context_facts に deprecated_reason を追加）の連鎖と SQL、モデルとの一致を検証するテスト。

Tests the revision chain and SQL of alembic migration 20261120_02, which adds deprecated_reason to
context_facts, and its agreement with the model.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from services.models import ContextFact

migration_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261120_02_add_context_fact_deprecated_reason.py"
)
spec = importlib.util.spec_from_file_location("context_fact_deprecated_reason_migration", migration_path)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the context fact deprecated reason migration.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


# 日本語: op.execute に渡された SQL を、空白を 1 つに揃えた文字列のリストにします。
# English: Return the SQL passed to op.execute with whitespace collapsed to single spaces.
def _statements(execute):
    return [" ".join(call.args[0].split()) for call in execute.call_args_list]


class ContextFactDeprecatedReasonMigrationTestCase(unittest.TestCase):
    def test_revision_follows_the_fact_sources_migration(self):
        self.assertEqual(migration.revision, "20261120_02")
        self.assertEqual(migration.down_revision, "20261120_01")

    def test_upgrade_adds_a_nullable_column_with_every_reason_allowed(self):
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()

        bound, alter, reset = _statements(execute)
        # 排他ロックの待ちに上限を付け、後続の revision へ持ち越さないよう最後に戻す。
        # The exclusive-lock wait is bounded and the limit is reset so it does not carry into later revisions.
        self.assertEqual(bound, "SET LOCAL lock_timeout = '5s'")
        self.assertEqual(reset, "SET LOCAL lock_timeout TO DEFAULT")
        self.assertIn("ADD COLUMN deprecated_reason VARCHAR(20),", alter)
        self.assertNotIn("NOT NULL", alter)
        self.assertNotIn("DEFAULT", alter)
        # 後から CHECK の値を足すには制約の削除が要り、安全検査に落ちるので、後続が使う値も最初から入れる。
        # Widening the CHECK later needs a DROP CONSTRAINT, so the values later changes use are allowed now.
        self.assertIn(
            "CHECK (deprecated_reason IS NULL OR deprecated_reason IN ('user', 'superseded', 'merged', 'capacity'))",
            alter,
        )

    def test_upgrade_does_not_touch_existing_rows(self):
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()

        self.assertFalse(any("UPDATE" in sql for sql in _statements(execute)))

    def test_downgrade_drops_the_column_and_constraint(self):
        with patch.object(migration.op, "execute") as execute:
            migration.downgrade()

        (statement,) = _statements(execute)
        self.assertIn("DROP CONSTRAINT IF EXISTS ck_context_facts_deprecated_reason", statement)
        self.assertIn("DROP COLUMN IF EXISTS deprecated_reason", statement)

    def test_model_matches_the_migration(self):
        column = ContextFact.__table__.c.deprecated_reason
        self.assertTrue(column.nullable)
        self.assertEqual(column.type.length, 20)
        check = next(
            constraint
            for constraint in ContextFact.__table__.constraints
            if constraint.name == "ck_context_facts_deprecated_reason"
        )
        self.assertIn("'user', 'superseded', 'merged', 'capacity'", str(check.sqltext))


if __name__ == "__main__":
    unittest.main()
