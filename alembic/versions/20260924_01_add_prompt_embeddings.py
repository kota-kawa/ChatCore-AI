"""Add embedding columns to public prompts for semantic search and recommendations.

Revision ID: 20260924_01
Revises: 20260923_03
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260924_01"
down_revision: Union[str, Sequence[str], None] = "20260923_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 追加のみ: 旧バージョンが読み書きしない列です。vector(768) は memo_entries /
    # context_facts と同じ次元で、services/embeddings.py の 1 つのモデル設定に揃えます。
    # embedding_status は backfill が未生成行を数えるための契約で、既存行は全て pending です。
    # Expand only: columns the previous color neither reads nor writes. vector(768) matches
    # memo_entries / context_facts so one model configuration in services/embeddings.py
    # serves every table. embedding_status lets the backfill count rows still waiting;
    # every existing prompt starts as pending.
    op.execute(
        """
        ALTER TABLE prompts
            ADD COLUMN IF NOT EXISTS embedding_vector vector(768),
            ADD COLUMN IF NOT EXISTS embedding_status VARCHAR(16) NOT NULL DEFAULT 'pending'
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
            ADD CONSTRAINT ck_prompts_embedding_status
            CHECK (embedding_status IN ('pending', 'ready')) NOT VALID
        """
    )
    op.execute("ALTER TABLE prompts VALIDATE CONSTRAINT ck_prompts_embedding_status")

    # 近傍検索の索引は書き込みを止めずに作ります。ベクトルが無い行は検索対象外なので除きます。
    # Build the nearest-neighbour index without blocking writes; rows without a vector are
    # never searched, so they stay out of the index.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_prompts_embedding_hnsw
                ON prompts USING hnsw (embedding_vector vector_cosine_ops)
                WHERE embedding_vector IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_prompts_embedding_hnsw")
    op.execute("ALTER TABLE prompts DROP CONSTRAINT IF EXISTS ck_prompts_embedding_status")
    op.execute(
        """
        ALTER TABLE prompts
            DROP COLUMN IF EXISTS embedding_status,
            DROP COLUMN IF EXISTS embedding_vector
        """
    )
