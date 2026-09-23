"""Add a pin timestamp to chat rooms.

Revision ID: 20260923_03
Revises: 20260923_02
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260923_03"
down_revision: Union[str, Sequence[str], None] = "20260923_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Expand only: a nullable column that the previous Blue/Green color neither reads nor writes.
    # NULL means "not pinned"; the timestamp orders the pinned section newest-pin first.
    # 追加のみ: 旧バージョンが読み書きしない NULL 許容の列です。
    # NULL はピン留めなしを表し、日時はピン留めした新しい順の並びに使います。
    op.execute(
        """
        ALTER TABLE chat_rooms
            ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMP
        """
    )
    # Pinned rooms are few per user, so a partial index keeps the pinned-section read cheap
    # without growing the index for every room.
    # ピン留めはユーザーあたり少数なので、部分インデックスで全ルーム分の索引を増やさずに読み出しを軽くします。
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_rooms_user_pinned_at
            ON chat_rooms (user_id, pinned_at DESC, id DESC)
            WHERE pinned_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_rooms_user_pinned_at")
    op.execute(
        """
        ALTER TABLE chat_rooms
            DROP COLUMN IF EXISTS pinned_at
        """
    )
