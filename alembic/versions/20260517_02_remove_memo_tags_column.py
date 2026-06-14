"""Remove memo tags column.

Revision ID: 20260517_02
Revises: 20260517_01
Create Date: 2026-05-17 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260517_02"
down_revision: Union[str, Sequence[str], None] = "20260517_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE memo_entries
            DROP COLUMN IF EXISTS tags
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE memo_entries
            ADD COLUMN IF NOT EXISTS tags VARCHAR(255) DEFAULT NULL
        """
    )
