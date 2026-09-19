import unittest
from pathlib import Path

from scripts.check_migration_safety import (
    BLOCKING_INDEX_LABEL,
    BLOCKING_INDEX_REVIEW_MARKER,
    DATA_REVIEW_MARKER,
    VALIDATED_CHECK_LABEL,
    VALIDATED_CHECK_REVIEW_MARKER,
    MigrationSource,
    check_migrations,
    classify_upgrade,
)


class MigrationSafetyTestCase(unittest.TestCase):
    def test_current_history_hardening_migration_is_reviewed_for_data_changes(self):
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
        # This revision's UPDATE statements are the reviewed backfill; the only
        # remaining finding is the CHECK-without-NOT-VALID pattern added below,
        # which is a known, already-applied violation (see
        # test_check_migrations_grandfathers_the_applied_history_hardening_check).
        self.assertEqual(classify_upgrade(migration), [VALIDATED_CHECK_LABEL])

    def test_check_migrations_grandfathers_the_applied_history_hardening_check(self):
        # 20260826_01 is already merged and applied; check_migrations() (the entry
        # point CI actually runs) must not fail the build over a violation that
        # can no longer be un-applied without rewriting history.
        violations_by_revision = {
            migration.revision: reasons for migration, reasons in check_migrations("20260824_03")
        }
        self.assertNotIn("20260826_01", violations_by_revision)

    def test_check_migrations_grandfathers_applied_blocking_indexes(self):
        violations_by_revision = {
            migration.revision: reasons for migration, reasons in check_migrations("20260824_03")
        }
        for revision in ("20260829_01", "20260901_01", "20260913_02"):
            self.assertNotIn(revision, violations_by_revision)

    def test_new_memory_facts_index_migration_passes_the_checker(self):
        # This revision uses its own explicit review marker rather than a
        # grandfather entry, since it is new work introduced on this branch.
        violations_by_revision = {
            migration.revision: reasons for migration, reasons in check_migrations("20260824_03")
        }
        self.assertNotIn("20260919_01", violations_by_revision)

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

    def test_raw_sql_create_index_without_concurrently_is_rejected(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source="""
def upgrade():
    op.execute("CREATE INDEX idx_users_email ON users (email)")

def downgrade():
    pass
""",
        )

        self.assertIn(BLOCKING_INDEX_LABEL, classify_upgrade(migration))

    def test_op_create_index_without_concurrently_kwarg_is_rejected(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source="""
def upgrade():
    op.create_index("idx_users_email", "users", ["email"])

def downgrade():
    pass
""",
        )

        self.assertIn(BLOCKING_INDEX_LABEL, classify_upgrade(migration))

    def test_op_create_index_with_concurrently_kwarg_is_accepted(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source="""
def upgrade():
    op.create_index(
        "idx_users_email", "users", ["email"], postgresql_concurrently=True
    )

def downgrade():
    pass
""",
        )

        self.assertNotIn(BLOCKING_INDEX_LABEL, classify_upgrade(migration))

    def test_create_index_on_a_table_created_in_the_same_upgrade_is_accepted(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source="""
def upgrade():
    op.create_table("widgets", sa.Column("id", sa.Integer()))
    op.create_index("idx_widgets_id", "widgets", ["id"])

def downgrade():
    pass
""",
        )

        self.assertNotIn(BLOCKING_INDEX_LABEL, classify_upgrade(migration))

    def test_blocking_index_with_review_marker_is_accepted(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source=f"""
{BLOCKING_INDEX_REVIEW_MARKER}
def upgrade():
    op.create_index("idx_users_email", "users", ["email"])

def downgrade():
    pass
""",
        )

        self.assertNotIn(BLOCKING_INDEX_LABEL, classify_upgrade(migration))

    def test_raw_sql_add_check_constraint_without_not_valid_is_rejected(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source="""
def upgrade():
    op.execute("ALTER TABLE users ADD CONSTRAINT ck_users_x CHECK (x > 0)")

def downgrade():
    pass
""",
        )

        self.assertIn(VALIDATED_CHECK_LABEL, classify_upgrade(migration))

    def test_raw_sql_add_check_constraint_with_not_valid_is_accepted(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source="""
def upgrade():
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_x CHECK (x > 0) NOT VALID"
    )

def downgrade():
    pass
""",
        )

        self.assertNotIn(VALIDATED_CHECK_LABEL, classify_upgrade(migration))

    def test_op_create_check_constraint_without_not_valid_kwarg_is_rejected(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source="""
def upgrade():
    op.create_check_constraint("ck_users_x", "users", "x > 0")

def downgrade():
    pass
""",
        )

        self.assertIn(VALIDATED_CHECK_LABEL, classify_upgrade(migration))

    def test_op_create_check_constraint_with_not_valid_kwarg_is_accepted(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source="""
def upgrade():
    op.create_check_constraint(
        "ck_users_x", "users", "x > 0", postgresql_not_valid=True
    )

def downgrade():
    pass
""",
        )

        self.assertNotIn(VALIDATED_CHECK_LABEL, classify_upgrade(migration))

    def test_validated_check_with_review_marker_is_accepted(self):
        migration = MigrationSource(
            revision="future",
            down_revision="baseline",
            path=Path("future.py"),
            source=f"""
{VALIDATED_CHECK_REVIEW_MARKER}
def upgrade():
    op.create_check_constraint("ck_users_x", "users", "x > 0")

def downgrade():
    pass
""",
        )

        self.assertNotIn(VALIDATED_CHECK_LABEL, classify_upgrade(migration))


if __name__ == "__main__":
    unittest.main()
