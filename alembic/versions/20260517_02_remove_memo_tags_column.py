"""Remove memo tags column.

Revision ID: 20260517_02
Revises: 20260517_01
Create Date: 2026-05-17 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260517_02"
down_revision: Union[str, Sequence[str], None] = "20260517_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove the 'tags' column from 'memo_entries' table
    # memo_entries テーブルから 'tags' カラムを削除する
    op.execute(
        """
        ALTER TABLE memo_entries
            DROP COLUMN IF EXISTS tags
        """
    )


def downgrade() -> None:
    # Add back the 'tags' column to 'memo_entries' table with a default NULL value
    # memo_entries テーブルに 'tags' カラムをデフォルト NULL で再度追加する
    op.execute(
        """
        ALTER TABLE memo_entries
            ADD COLUMN IF NOT EXISTS tags VARCHAR(255) DEFAULT NULL
        """
    )
