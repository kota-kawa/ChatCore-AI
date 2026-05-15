"""Remove memo input_content column.

Revision ID: 20260515_01
Revises: 20260512_01
Create Date: 2026-05-15 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260515_01"
down_revision: Union[str, Sequence[str], None] = "20260512_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE memo_entries
            DROP COLUMN IF EXISTS input_content
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE memo_entries
            ADD COLUMN IF NOT EXISTS input_content TEXT NOT NULL DEFAULT ''
        """
    )
