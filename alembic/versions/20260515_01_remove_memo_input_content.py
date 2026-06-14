"""Remove memo input_content column.

Revision ID: 20260515_01
Revises: 20260512_01
Create Date: 2026-05-15 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260515_01"
down_revision: Union[str, Sequence[str], None] = "20260512_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove the 'input_content' column from 'memo_entries' table
    # memo_entries テーブルから 'input_content' カラムを削除する
    op.execute(
        """
        ALTER TABLE memo_entries
            DROP COLUMN IF EXISTS input_content
        """
    )


def downgrade() -> None:
    # Add back the 'input_content' column to 'memo_entries' table with a default empty string
    # memo_entries テーブルに 'input_content' カラムをデフォルト空文字で再度追加する
    op.execute(
        """
        ALTER TABLE memo_entries
            ADD COLUMN IF NOT EXISTS input_content TEXT NOT NULL DEFAULT ''
        """
    )
