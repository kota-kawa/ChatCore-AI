import unittest
from pathlib import Path

from scripts.check_migration_safety import (
    DATA_REVIEW_MARKER,
    MigrationSource,
    classify_upgrade,
)


class MigrationSafetyTestCase(unittest.TestCase):
    def test_current_history_hardening_migration_is_reviewed(self):
        path = (
            Path(__file__).parents[2]
            / "alembic"
            / "versions"
            / "20260826_01_harden_history_and_embedding_contracts.py"
        )
        source = path.read_text(encoding="utf-8")
        migration = MigrationSource(
            revision="20260826_01",
            down_revision="20260824_03",
            path=path,
            source=source,
        )

        self.assertIn(DATA_REVIEW_MARKER, source)
        self.assertEqual(classify_upgrade(migration), [])

    def test_unreviewed_update_is_rejected(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source="""
def upgrade():
    op.execute("UPDATE users SET username = 'x'")

def downgrade():
    pass
""",
        )

        self.assertIn("unreviewed UPDATE data change", classify_upgrade(migration))

    def test_drop_column_is_rejected_even_with_data_review_marker(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source=f"""
{DATA_REVIEW_MARKER}
def upgrade():
    op.execute("ALTER TABLE users DROP COLUMN bio")

def downgrade():
    pass
""",
        )

        self.assertIn("DROP TABLE/COLUMN/CONSTRAINT/INDEX", classify_upgrade(migration))


if __name__ == "__main__":
    unittest.main()
