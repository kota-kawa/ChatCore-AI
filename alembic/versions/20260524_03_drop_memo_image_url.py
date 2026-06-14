"""Drop memo image URL field.

Revision ID: 20260524_03
Revises: 20260524_02
Create Date: 2026-05-24 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260524_03"
down_revision: Union[str, Sequence[str], None] = "20260524_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop 'image_url' column from 'memo_entries' table
    # memo_entries テーブルから 'image_url' カラムを削除する
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS image_url")


def downgrade() -> None:
    # Add back 'image_url' column to 'memo_entries' table with a default NULL
    # memo_entries テーブルに 'image_url' カラムをデフォルト NULL で再度追加する
    op.execute("ALTER TABLE memo_entries ADD COLUMN IF NOT EXISTS image_url VARCHAR(255) NULL")
