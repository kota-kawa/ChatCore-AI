"""Add memo revisions and MCP-oriented search indexes.

Revision ID: 20260716_02
Revises: 20260716_01
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260716_02"
down_revision: Union[str, Sequence[str], None] = "20260716_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add optimistic-concurrency state and indexes used by MCP reads."""
    op.execute(
        """
        ALTER TABLE memo_entries
        ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1
        """
    )

    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memo_entries_user_updated_id
                ON memo_entries (user_id, updated_at DESC, id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_prompts_public_skill_markdown_trgm
                ON prompts USING gin (
                    (COALESCE(attributes ->> 'skill_markdown', '')) gin_trgm_ops
                )
                WHERE is_public = TRUE
                  AND deleted_at IS NULL
                  AND content_format = 'skill'
            """
        )


def downgrade() -> None:
    """Remove MCP-oriented indexes and memo revision state."""
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS idx_prompts_public_skill_markdown_trgm"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS idx_memo_entries_user_updated_id"
        )

    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS revision")
