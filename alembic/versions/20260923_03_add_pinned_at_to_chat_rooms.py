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
    # No dedicated index: the pinned-section read filters by user_id, which the existing
    # idx_chat_rooms_user_last_activity_id already narrows to one user's rooms. Building an
    # index here would block writes to chat_rooms (updated on every message) for the whole
    # scan, or with CONCURRENTLY give up the per-revision transaction.
    # 専用の索引は作りません。ピン留めの読み出しは user_id で絞るため、既存の
    # idx_chat_rooms_user_last_activity_id で1ユーザー分に収まります。ここで索引を作ると、
    # メッセージごとに更新される chat_rooms への書き込みを走査の間止めるか、CONCURRENTLY で
    # revision 単位のトランザクションを失うことになります。


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_rooms
            DROP COLUMN IF EXISTS pinned_at
        """
    )
