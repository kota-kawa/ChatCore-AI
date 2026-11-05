"""ユーザーの希望ロケール列を追加する Alembic migration の upgrade / downgrade が、繰り返し実行しても安全（冪
等）であることを検証するテスト。

Tests that the Alembic migration adding the user's preferred locale column has idempotent upgrade and downgrade.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260728_01_add_preferred_locale_to_users.py"
)


# migration ファイルを importlib で読み込み、モジュールとして返す。
# Loads the migration file with importlib and returns it as a module.
def load_migration():
    spec = importlib.util.spec_from_file_location("preferred_locale_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# op.execute をモックして、実行される SQL を確かめる。
# Mocks op.execute and checks the SQL that runs.
class PreferredLocaleMigrationTestCase(unittest.TestCase):
    def test_upgrade_and_downgrade_are_idempotent(self):
        migration = load_migration()
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()
            migration.downgrade()
        self.assertIn(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_locale VARCHAR(16) NULL",
            " ".join(execute.call_args_list[0].args[0].split()),
        )
        self.assertIn(
            "ALTER TABLE users DROP COLUMN IF EXISTS preferred_locale",
            " ".join(execute.call_args_list[1].args[0].split()),
        )


if __name__ == "__main__":
    unittest.main()
