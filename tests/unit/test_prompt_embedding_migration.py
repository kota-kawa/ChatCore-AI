"""プロンプトの埋め込みベクトル列を追加する Alembic マイグレーション（20260924_01）の内容を、ソース文字列で検証するテスト。

Tests the contents of the Alembic migration 20260924_01 that adds prompt embedding columns, by inspecting its source text.
"""

import unittest
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260924_01_add_prompt_embeddings.py"
)


# マイグレーションの親リビジョン、ベクトル列・状態列・並行作成インデックスの定義を検証するテストクラス。
# Test class for the migration's parent revision and its vector column, status column and concurrent index.
class PromptEmbeddingMigrationTestCase(unittest.TestCase):
    def test_migration_adds_vector_status_and_concurrent_index(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

        self.assertIn('revision: str = "20260924_01"', source)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "20260923_03"', source)
        self.assertIn("ADD COLUMN IF NOT EXISTS embedding_vector vector(768)", upgrade)
        self.assertIn("embedding_status VARCHAR(16) NOT NULL DEFAULT 'pending'", upgrade)
        self.assertIn("ck_prompts_embedding_status", upgrade)
        self.assertIn("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_prompts_embedding_hnsw", upgrade)
        self.assertIn("vector_cosine_ops", upgrade)


if __name__ == "__main__":
    unittest.main()
