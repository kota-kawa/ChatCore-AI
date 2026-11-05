"""共有スキルの取り込み元を記録する Alembic マイグレーション（20260829_01）の内容を検証するテスト。

Tests the contents of the Alembic migration 20260829_01 that records the shared prompt a user skill was imported from.
"""

import unittest
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260829_01_link_user_skills_to_shared_prompts.py"
)


# NULL 可の出典列と検索用インデックスの追加、および取り込みの出典を守るためダウングレードを禁止していることを検証するテストクラス。
# Test class for the nullable source column and lookup index, and for the downgrade being blocked to protect import provenance.
class SharedSkillProvenanceMigrationTests(unittest.TestCase):
    def test_migration_adds_nullable_source_and_lookup_index(self):
        source = MIGRATION.read_text(encoding="utf-8")
        upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        self.assertIn('sa.Column("source_prompt_id", sa.Integer(), nullable=True)', upgrade)
        self.assertIn('ondelete="SET NULL"', upgrade)
        self.assertIn('"idx_user_skills_user_source_prompt"', upgrade)
        self.assertNotIn("CREATE UNIQUE INDEX", upgrade)

    def test_downgrade_is_explicitly_blocked_to_protect_import_provenance(self):
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("intentionally irreversible", source)


if __name__ == "__main__":
    unittest.main()
