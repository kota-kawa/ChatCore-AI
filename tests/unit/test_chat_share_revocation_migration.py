import unittest
from pathlib import Path

from services.models import SharedChatRoom

MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260913_01_add_chat_share_link_revocation.py"
)


class ChatShareRevocationMigrationTestCase(unittest.TestCase):
    def test_migration_expands_shared_chat_rooms_with_lifecycle_columns(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

        self.assertIn('revision: str = "20260913_01"', source)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "20260901_01"', source)
        self.assertIn('"shared_chat_rooms"', upgrade)
        self.assertIn('sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)', upgrade)
        self.assertIn('sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)', upgrade)
        # expand/contract: 追加のみで、既存の列やインデックスには触れない。
        # Expand/contract: additive only, never touching existing columns or indexes.
        self.assertNotIn("DROP", upgrade.upper())

    def test_model_matches_the_migrated_columns(self):
        columns = SharedChatRoom.__table__.columns
        self.assertIn("expires_at", columns)
        self.assertIn("revoked_at", columns)
        for name in ("expires_at", "revoked_at"):
            with self.subTest(column=name):
                self.assertTrue(columns[name].nullable)
                self.assertTrue(columns[name].type.timezone)


if __name__ == "__main__":
    unittest.main()
