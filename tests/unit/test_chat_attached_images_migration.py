import unittest
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260923_02_add_attached_images_to_chat_history.py"
)


class ChatAttachedImagesMigrationTestCase(unittest.TestCase):
    def test_migration_adds_nullable_jsonb_column_and_drops_it_on_downgrade(self):
        sql = MIGRATION_PATH.read_text()

        self.assertIn('revision: str = "20260923_02"', sql)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "20260923_01"', sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS attached_images JSONB", sql)
        self.assertNotIn("NOT NULL", sql)
        self.assertIn("DROP COLUMN IF EXISTS attached_images", sql)


if __name__ == "__main__":
    unittest.main()
