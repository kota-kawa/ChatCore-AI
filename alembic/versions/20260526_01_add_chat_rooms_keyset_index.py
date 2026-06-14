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


# 日本語: upgrade のスキーマ更新処理を担当します。
# English: Handle upgrading schema for upgrade.
def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_rooms_user_created_at_id
            ON chat_rooms (user_id, created_at DESC, id DESC)
        """
    )


# 日本語: downgrade のスキーマ差し戻し処理を担当します。
# English: Handle downgrading schema for downgrade.
def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_rooms_user_created_at_id")
