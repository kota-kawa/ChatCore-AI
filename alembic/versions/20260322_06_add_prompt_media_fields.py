"""Add prompt type and reference image fields to prompts.

Revision ID: 20260322_06
Revises: 20260322_05
Create Date: 2026-03-22 16:40:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260322_06"
down_revision: Union[str, Sequence[str], None] = "20260322_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS prompt_type VARCHAR(20) NOT NULL DEFAULT 'text'
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS reference_image_url VARCHAR(255) NULL DEFAULT NULL
        """
    )
    op.execute(
        """
        UPDATE prompts
           SET prompt_type = 'text'
         WHERE prompt_type IS NULL OR prompt_type = ''
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS reference_image_url
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS prompt_type
        """
    )
