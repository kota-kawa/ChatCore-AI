from pathlib import Path
import unittest


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260829_01_link_user_skills_to_shared_prompts.py"
)


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
