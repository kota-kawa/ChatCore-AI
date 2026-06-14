"""Add extracted attachment content to chat history.

Revision ID: 20260603_01
Revises: 20260527_01
Create Date: 2026-06-03 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260603_01"
down_revision: Union[str, Sequence[str], None] = "20260527_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'attached_file_contents' column (JSONB) to 'chat_history' table to store parsed/extracted content of file attachments
    # 添付ファイルの解析・抽出された内容を保存するため、chat_history テーブルに 'attached_file_contents' カラム (JSONB) を追加する
    op.execute(
        """
        ALTER TABLE chat_history
            ADD COLUMN IF NOT EXISTS attached_file_contents JSONB
        """
    )


def downgrade() -> None:
    # Remove 'attached_file_contents' column from 'chat_history' table
    # chat_history テーブルから 'attached_file_contents' カラムを削除する
    op.execute(
        """
        ALTER TABLE chat_history
            DROP COLUMN IF EXISTS attached_file_contents
        """
    )
