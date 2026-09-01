import unittest
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260901_01_add_chat_room_last_activity.py"
)


class ChatRoomActivityMigrationTestCase(unittest.TestCase):
    def test_migration_adds_and_backfills_activity_ordering(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

        self.assertIn('revision: str = "20260901_01"', source)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "20260829_02"', source)
        self.assertIn('"last_activity_at"', upgrade)
        self.assertIn("MAX(history.timestamp)", upgrade)
        self.assertIn("idx_chat_rooms_user_last_activity_id", upgrade)
        self.assertIn("last_activity_at DESC", upgrade)


if __name__ == "__main__":
    unittest.main()
