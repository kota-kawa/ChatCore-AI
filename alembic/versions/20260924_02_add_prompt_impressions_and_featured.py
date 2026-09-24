"""Count prompt card impressions and let operators pin featured prompts.

Revision ID: 20260924_02
Revises: 20260924_01
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260924_02"
down_revision: Union[str, Sequence[str], None] = "20260924_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # カードが画面に出た回数。prompt_view_counts と同じく、投稿の編集日時や履歴を
    # 動かさない専用カウンターに置く。閲覧数と並べるとクリック率が出せる。
    # How often a card was shown. Like prompt_view_counts this lives in its own counter so
    # it never touches the prompt's edit timestamp or history; next to view_count it yields
    # a click-through rate.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_impression_counts (
            prompt_id INTEGER PRIMARY KEY,
            impression_count BIGINT NOT NULL DEFAULT 0,
            CONSTRAINT fk_prompt_impression_counts_prompt
                FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
            CONSTRAINT ck_prompt_impression_counts_non_negative
                CHECK (impression_count >= 0)
        )
        """
    )
    # 追加のみ: 運営が選んだ投稿の日時。NULL は通常の投稿。旧バージョンは読み書きしない。
    # Expand only: when an operator featured the prompt; NULL means an ordinary post. The
    # previous color neither reads nor writes it.
    op.execute(
        """
        ALTER TABLE prompts
            ADD COLUMN IF NOT EXISTS featured_at TIMESTAMP
        """
    )
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_prompts_featured
                ON prompts (featured_at DESC, id DESC)
                WHERE featured_at IS NOT NULL AND is_public = TRUE AND deleted_at IS NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_prompts_featured")
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS featured_at")
    op.execute("DROP TABLE IF EXISTS prompt_impression_counts")
