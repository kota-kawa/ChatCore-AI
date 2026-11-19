"""alembic マイグレーション 20261119_01（記憶の自動抽出を初期オンにし、既存ユーザーも全員オンにする）
のリビジョン連鎖と upgrade/downgrade の SQL、およびモデルの初期値との一致を検証するテスト。

Tests the revision chain and the upgrade/downgrade SQL of alembic migration 20261119_01, which turns memory
auto-extraction on by default and for every existing user, plus agreement with the model's server default.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from services.models import User

migration_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261119_01_default_context_auto_extract_on.py"
)
spec = importlib.util.spec_from_file_location("context_auto_extract_default_on_migration", migration_path)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the extraction default migration.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


# 日本語: op.execute に渡された SQL を、空白を 1 つに揃えた文字列のリストにします。
# English: Return the SQL passed to op.execute with whitespace collapsed to single spaces.
def _normalized_statements(execute):
    return [" ".join(call.args[0].split()) for call in execute.call_args_list]


# 日本語: マイグレーション関数は op をモックして呼び、発行される SQL だけを確認します。
# English: The migration functions are called with op mocked, and only the emitted SQL is checked.
class ContextAutoExtractDefaultOnMigrationTestCase(unittest.TestCase):
    def test_revision_follows_demo_access_codes(self):
        self.assertEqual(migration.revision, "20261119_01")
        self.assertEqual(migration.down_revision, "20261028_01")

    def test_upgrade_flips_default_and_enables_existing_users(self):
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()

        self.assertEqual(
            _normalized_statements(execute),
            [
                "ALTER TABLE users ALTER COLUMN context_auto_extract_enabled SET DEFAULT TRUE",
                "UPDATE users SET context_auto_extract_enabled = TRUE WHERE context_auto_extract_enabled = FALSE",
            ],
        )

    def test_downgrade_restores_only_the_column_default(self):
        with patch.object(migration.op, "execute") as execute:
            migration.downgrade()

        # 個別の設定値は復元できないので、UPDATE は発行しない。
        # Per-user values cannot be restored, so no UPDATE is issued.
        self.assertEqual(
            _normalized_statements(execute),
            ["ALTER TABLE users ALTER COLUMN context_auto_extract_enabled SET DEFAULT FALSE"],
        )

    def test_model_server_default_matches_the_migration(self):
        server_default = User.__table__.c.context_auto_extract_enabled.server_default
        self.assertEqual(str(server_default.arg).upper(), "TRUE")


if __name__ == "__main__":
    unittest.main()
