"""Add structured message parts to chat history.

Revision ID: 20260527_01
Revises: 20260526_01
Create Date: 2026-05-27 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260527_01"
down_revision: Union[str, Sequence[str], None] = "20260526_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'message_parts' column (JSONB) to 'chat_history' table to store structured rich/multi-part message contents
    # 構造化されたマルチパートメッセージコンテンツを保存するため、chat_history テーブルに 'message_parts' カラム (JSONB) を追加する
    op.execute(
        """
        ALTER TABLE chat_history
            ADD COLUMN IF NOT EXISTS message_parts JSONB
        """
    )


def downgrade() -> None:
    # Remove 'message_parts' column from 'chat_history' table
    # chat_history テーブルから 'message_parts' カラムを削除する
    op.execute(
        """
        ALTER TABLE chat_history
            DROP COLUMN IF EXISTS message_parts
        """
    )
