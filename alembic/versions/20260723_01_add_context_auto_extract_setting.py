"""Add the personal-context automatic extraction preference.

Revision ID: 20260723_01
Revises: 20260720_01
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260723_01"
down_revision: Union[str, Sequence[str], None] = "20260720_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add an opt-in preference so extraction never starts silently."""
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS context_auto_extract_enabled BOOLEAN NOT NULL DEFAULT FALSE
        """
    )


def downgrade() -> None:
    """Remove the personal-context extraction preference."""
    op.execute(
        """
        ALTER TABLE users
        DROP COLUMN IF EXISTS context_auto_extract_enabled
        """
    )
