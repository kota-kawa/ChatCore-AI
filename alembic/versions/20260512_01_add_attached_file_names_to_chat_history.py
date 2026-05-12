"""Add attached_file_names column to chat_history.

Revision ID: 20260512_01
Revises: 20260511_01
Create Date: 2026-05-12 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260512_01"
down_revision: Union[str, Sequence[str], None] = "20260511_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_history
            ADD COLUMN IF NOT EXISTS attached_file_names TEXT
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_history
            DROP COLUMN IF EXISTS attached_file_names
        """
    )
