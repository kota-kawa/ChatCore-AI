"""alembic マイグレーション 20260723_01（users に context_auto_extract_enabled を追加）
のリビジョン連鎖と upgrade/downgrade の SQL を検証するテスト。

Tests the revision chain and the upgrade/downgrade SQL of alembic migration 20260723_01, which adds
users.context_auto_extract_enabled.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

migration_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260723_01_add_context_auto_extract_setting.py"
)
spec = importlib.util.spec_from_file_location(
    "context_auto_extract_migration",
    migration_path,
)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the context extraction preference migration.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


# 日本語: op.execute に渡された SQL を、空白を 1 つに揃えた文字列のリストにします。
# English: Return the SQL passed to op.execute with whitespace collapsed to single spaces.
def _normalized_statements(execute):
    return [" ".join(call.args[0].split()) for call in execute.call_args_list]


# 日本語: マイグレーション関数は op をモックして呼び、発行される SQL だけを確認します。
# English: The migration functions are called with op mocked, and only the emitted SQL is checked.
class ContextAutoExtractMigrationTestCase(unittest.TestCase):
    def test_revision_follows_context_candidate_foundation(self):
        self.assertEqual(migration.revision, "20260723_01")
        self.assertEqual(migration.down_revision, "20260720_01")

    def test_upgrade_adds_disabled_by_default_opt_in(self):
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()

        self.assertEqual(
            _normalized_statements(execute),
            [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "context_auto_extract_enabled BOOLEAN NOT NULL DEFAULT FALSE"
            ],
        )

    def test_downgrade_removes_preference_idempotently(self):
        with patch.object(migration.op, "execute") as execute:
            migration.downgrade()

        self.assertEqual(
            _normalized_statements(execute),
            [
                "ALTER TABLE users DROP COLUMN IF EXISTS "
                "context_auto_extract_enabled"
            ],
        )


if __name__ == "__main__":
    unittest.main()
