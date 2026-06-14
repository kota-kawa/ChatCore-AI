"""Expand user profile columns from VARCHAR(255) to TEXT.

Revision ID: 20260502_01
Revises: 20260501_01
Create Date: 2026-05-02 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260502_01"
down_revision: Union[str, Sequence[str], None] = "20260501_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ALTER COLUMN avatar_url TYPE TEXT,
            ALTER COLUMN username   TYPE TEXT
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ALTER COLUMN avatar_url TYPE VARCHAR(255),
            ALTER COLUMN username   TYPE VARCHAR(255)
        """
    )
