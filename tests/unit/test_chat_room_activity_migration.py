"""チャットルームの last_activity_at 追加 migration（20260901_01）の内容を検証するテスト。

Tests the contents of the chat room last_activity_at migration (20260901_01).
"""

import unittest
from pathlib import Path

# 検証対象の Alembic migration ファイル。
# The Alembic migration file under test.
MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260901_01_add_chat_room_last_activity.py"
)


class ChatRoomActivityMigrationTestCase(unittest.TestCase):
    # DB に接続せず migration のソースを文字列で調べ、列の追加・既存履歴からの埋め戻し・並び替え用インデックスを確認する。
    # Inspects the migration source as text, without a DB, for the added column, the backfill from existing history and the ordering index.
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
