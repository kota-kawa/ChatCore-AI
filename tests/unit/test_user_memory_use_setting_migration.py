"""alembic マイグレーション 20261120_04（users に memory_use_enabled を追加）の連鎖と SQL、モデルとの一致を検証するテスト。

Tests the revision chain and SQL of alembic migration 20261120_04, which adds users.memory_use_enabled,
and its agreement with the model.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from services.models import User

migration_path = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261120_04_add_user_memory_use_setting.py"
)
spec = importlib.util.spec_from_file_location("user_memory_use_setting_migration", migration_path)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the memory use setting migration.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


# 日本語: op.execute に渡された SQL を、空白を 1 つに揃えた文字列のリストにします。
# English: Return the SQL passed to op.execute with whitespace collapsed to single spaces.
def _statements(execute):
    return [" ".join(call.args[0].split()) for call in execute.call_args_list]


class UserMemoryUseSettingMigrationTestCase(unittest.TestCase):
    def test_revision_follows_the_candidate_promotion_migration(self):
        self.assertEqual(migration.revision, "20261120_04")
        self.assertEqual(migration.down_revision, "20261120_03")

    def test_upgrade_adds_the_column_on_by_default_inside_a_bounded_lock_wait(self):
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()

        bound, alter, reset = _statements(execute)
        # users は全リクエストの認証で読まれる。排他ロックの待ちに上限を付け、後続の revision へ持ち越さないよう最後に戻す。
        # users is read on every authenticated request; the exclusive-lock wait is bounded and reset at the end.
        self.assertEqual(bound, "SET LOCAL lock_timeout = '5s'")
        self.assertEqual(reset, "SET LOCAL lock_timeout TO DEFAULT")
        self.assertEqual(
            alter,
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS memory_use_enabled BOOLEAN NOT NULL DEFAULT TRUE",
        )

    def test_upgrade_does_not_rewrite_existing_rows(self):
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()

        self.assertFalse(any("UPDATE" in sql for sql in _statements(execute)))

    def test_downgrade_is_refused_because_it_would_discard_every_preference(self):
        with self.assertRaises(RuntimeError):
            migration.downgrade()

    def test_model_matches_the_migration(self):
        column = User.__table__.c.memory_use_enabled
        self.assertFalse(column.nullable)
        self.assertEqual(str(column.server_default.arg), "TRUE")


if __name__ == "__main__":
    unittest.main()
