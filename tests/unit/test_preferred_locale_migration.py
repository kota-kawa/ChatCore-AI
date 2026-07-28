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


def load_migration():
    spec = importlib.util.spec_from_file_location("preferred_locale_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
