"""Add ai_model column to prompts table.

Revision ID: 20260322_05
Revises: 20260322_04
Create Date: 2026-03-22 14:00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260322_05"
down_revision: Union[str, Sequence[str], None] = "20260322_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS ai_model VARCHAR(100) NULL DEFAULT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS ai_model
        """
    )
