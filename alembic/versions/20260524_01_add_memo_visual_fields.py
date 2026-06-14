"""Add memo background color field.

Revision ID: 20260524_01
Revises: 20260518_01
Create Date: 2026-05-24 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260524_01"
down_revision: Union[str, Sequence[str], None] = "20260518_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'background_color' column to 'memo_entries' table to store visual styling choices
    # メモの背景色（スタイリング設定）を保存するため、memo_entries テーブルに 'background_color' カラムを追加する
    op.execute(
        """
        ALTER TABLE memo_entries
            ADD COLUMN IF NOT EXISTS background_color VARCHAR(20) NULL
        """
    )


def downgrade() -> None:
    # Remove 'background_color' column from 'memo_entries' table
    # memo_entries テーブルから 'background_color' カラムを削除する
    op.execute(
        """
        ALTER TABLE memo_entries
            DROP COLUMN IF EXISTS background_color
        """
    )
