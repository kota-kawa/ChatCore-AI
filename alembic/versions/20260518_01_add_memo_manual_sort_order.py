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


def upgrade() -> None:
    # 1. Add the 'sort_order' column to the 'memo_entries' table
    # 1. memo_entries テーブルに 'sort_order' カラムを追加する
    op.execute(
        """
        ALTER TABLE memo_entries
            ADD COLUMN IF NOT EXISTS sort_order NUMERIC(20, 6)
        """
    )
    # 2. Populate the 'sort_order' using the unix epoch of the 'created_at' timestamp
    # 2. 既存のデータの 'sort_order' に 'created_at' の Unix エポック値を設定する
    op.execute(
        """
        UPDATE memo_entries
        SET sort_order = EXTRACT(EPOCH FROM created_at)::numeric
        WHERE sort_order IS NULL
        """
    )
    # 3. Create a composite index to optimize memo sorting and filtering
    # 3. メモの並び替えとフィルタリングを最適化するために複合インデックスを作成する
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memo_entries_user_archived_pinned_sort
            ON memo_entries (user_id, archived_at, pinned_at, sort_order DESC)
        """
    )


def downgrade() -> None:
    # 1. Drop the composite index for memo sorting
    # 1. メモの並び替え用複合インデックスを削除する
    op.execute("DROP INDEX IF EXISTS idx_memo_entries_user_archived_pinned_sort")
    # 2. Drop the 'sort_order' column from the 'memo_entries' table
    # 2. memo_entries テーブルから 'sort_order' カラムを削除する
    op.execute(
        """
        ALTER TABLE memo_entries
            DROP COLUMN IF EXISTS sort_order
        """
    )
