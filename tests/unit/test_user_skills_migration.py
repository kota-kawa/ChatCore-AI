import unittest
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260828_01_add_user_skills.py"
PROMPT_TOOLS_MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260928_01_add_prompt_tools_skill_column.py"
)


class UserSkillsMigrationTests(unittest.TestCase):
    def test_migration_adds_expand_only_schema_and_uses_safe_index_operation(self):
        source = MIGRATION.read_text(encoding="utf-8")
        upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        self.assertIn('op.create_table(\n        "user_skills"', upgrade)
        self.assertIn('sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE")', upgrade)
        self.assertIn('op.create_index(\n        "uq_user_skills_user_normalized_name"', upgrade)
        self.assertNotIn("CREATE UNIQUE INDEX", upgrade)

    def test_downgrade_is_explicitly_blocked_to_protect_user_data(self):
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("intentionally irreversible", source)
        self.assertNotIn('op.drop_table("user_skills")', source)

    def test_prompt_tools_skill_preference_is_added_with_a_default_and_no_data_losing_downgrade(self):
        source = PROMPT_TOOLS_MIGRATION.read_text(encoding="utf-8")
        upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        self.assertIn('op.add_column(\n        "users"', upgrade)
        self.assertIn('"prompt_tools_skill_enabled"', upgrade)
        self.assertIn("nullable=False", upgrade)
        self.assertIn("server_default=sa.text(\"TRUE\")", upgrade)
        self.assertIn("intentionally irreversible", source)
        self.assertNotIn('op.drop_column("prompt_tools_skill_enabled")', source)


if __name__ == "__main__":
    unittest.main()
