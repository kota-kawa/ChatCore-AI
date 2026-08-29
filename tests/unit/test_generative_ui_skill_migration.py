from pathlib import Path
import unittest


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260829_02_add_generative_ui_skill_preference.py"
)


class GenerativeUiSkillMigrationTests(unittest.TestCase):
    def test_migration_adds_default_enabled_user_preference(self):
        source = MIGRATION.read_text(encoding="utf-8")
        upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

        self.assertIn('"generative_ui_skill_enabled"', upgrade)
        self.assertIn("nullable=False", upgrade)
        self.assertIn('server_default=sa.text("TRUE")', upgrade)

    def test_downgrade_preserves_user_preferences(self):
        source = MIGRATION.read_text(encoding="utf-8")

        self.assertIn("intentionally irreversible", source)
        self.assertNotIn('op.drop_column("users"', source)


if __name__ == "__main__":
    unittest.main()
