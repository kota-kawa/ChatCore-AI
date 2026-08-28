from pathlib import Path
import unittest


MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260828_01_add_user_skills.py"


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


if __name__ == "__main__":
    unittest.main()
