"""Add LLM profile context field to users.

Revision ID: 20260420_02
Revises: 20260420_01
Create Date: 2026-04-20 13:10:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260420_02"
down_revision: Union[str, Sequence[str], None] = "20260420_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS llm_profile_context TEXT
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        DROP COLUMN IF EXISTS llm_profile_context
        """
    )
