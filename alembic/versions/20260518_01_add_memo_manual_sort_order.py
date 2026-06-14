"""Add manual sort order for memo cards.

Revision ID: 20260518_01
Revises: 20260517_02
Create Date: 2026-05-18 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260518_01"
down_revision: Union[str, Sequence[str], None] = "20260517_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 日本語: upgrade のスキーマ更新処理を担当します。
# English: Handle upgrading schema for upgrade.
def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE memo_entries
            ADD COLUMN IF NOT EXISTS sort_order NUMERIC(20, 6)
        """
    )
    op.execute(
        """
        UPDATE memo_entries
        SET sort_order = EXTRACT(EPOCH FROM created_at)::numeric
        WHERE sort_order IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memo_entries_user_archived_pinned_sort
            ON memo_entries (user_id, archived_at, pinned_at, sort_order DESC)
        """
    )


# 日本語: downgrade のスキーマ差し戻し処理を担当します。
# English: Handle downgrading schema for downgrade.
def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memo_entries_user_archived_pinned_sort")
    op.execute(
        """
        ALTER TABLE memo_entries
            DROP COLUMN IF EXISTS sort_order
        """
    )
