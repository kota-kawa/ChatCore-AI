"""chat_history に attached_images 列(NULL 許可の JSONB)を追加する Alembic マイグレーションの内容(リビジョン、
追加・削除 SQL)を、ファイル内容の文字列で検証する単体テスト。

Unit test that checks, by file contents, the Alembic migration adding the nullable JSONB attached_images column
to chat_history (revision ids and the add/drop SQL).
"""

import unittest
from pathlib import Path

# 日本語: 対象マイグレーション(2026-09-23 の attached_images 追加)のファイルパス。
# English: Path to the migration under test (the 2026-09-23 attached_images addition).
MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260923_02_add_attached_images_to_chat_history.py"
)


# 日本語: 実行時に DB は使わず、マイグレーション .py のソースを読んで、リビジョン連鎖と NULL 許可・ダウングレードの SQL を確かめる。
# English: Uses no database; reads the migration source and checks the revision chain, nullability and the downgrade SQL.
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
