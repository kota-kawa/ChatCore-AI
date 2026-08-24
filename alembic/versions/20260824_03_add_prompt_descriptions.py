"""Add optional plain-text descriptions to shared prompts.

Revision ID: 20260824_03
Revises: 20260824_02
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260824_03"
down_revision: Union[str, Sequence[str], None] = "20260824_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a nullable, bounded description while keeping existing posts unchanged."""
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS description VARCHAR(300) NULL DEFAULT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_public_description_trgm
            ON prompts USING gin (description gin_trgm_ops)
            WHERE is_public = TRUE AND description IS NOT NULL
        """
    )


def downgrade() -> None:
    """Remove the optional description and its public search index."""
    op.execute("DROP INDEX IF EXISTS idx_prompts_public_description_trgm")
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS description")
