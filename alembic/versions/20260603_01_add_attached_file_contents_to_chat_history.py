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


# 日本語: upgrade のスキーマ更新処理を担当します。
# English: Handle upgrading schema for upgrade.
def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_history
            ADD COLUMN IF NOT EXISTS attached_file_contents JSONB
        """
    )


# 日本語: downgrade のスキーマ差し戻し処理を担当します。
# English: Handle downgrading schema for downgrade.
def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_history
            DROP COLUMN IF EXISTS attached_file_contents
        """
    )
