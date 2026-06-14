"""Add chat room keyset pagination index.

Revision ID: 20260526_01
Revises: 20260524_03
Create Date: 2026-05-26 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260526_01"
down_revision: Union[str, Sequence[str], None] = "20260524_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create a composite index on chat_rooms to optimize keyset-based pagination sorting by user_id and created_at/id descending
    # user_id および作成日時の降順・IDの降順でソートするキーセット型ページネーションを最適化するため、chat_rooms テーブルに複合インデックスを作成する
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_rooms_user_created_at_id
            ON chat_rooms (user_id, created_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    # Drop the keyset pagination index from chat_rooms
    # chat_rooms テーブルからキーセットページネーション用のインデックスを削除する
    op.execute("DROP INDEX IF EXISTS idx_chat_rooms_user_created_at_id")
