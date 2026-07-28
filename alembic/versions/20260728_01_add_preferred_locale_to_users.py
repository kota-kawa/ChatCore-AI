"""Add the user's preferred locale.

Revision ID: 20260728_01
Revises: 20260724_01
Create Date: 2026-07-28
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260728_01"
down_revision: Union[str, Sequence[str], None] = "20260724_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a nullable locale so existing users remain on automatic detection."""
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS preferred_locale VARCHAR(16) NULL
        """
    )


def downgrade() -> None:
    """Remove the preferred locale."""
    op.execute(
        """
        ALTER TABLE users
        DROP COLUMN IF EXISTS preferred_locale
        """
    )
