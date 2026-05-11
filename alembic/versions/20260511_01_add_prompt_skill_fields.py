"""Add SKILL content fields to prompts.

Revision ID: 20260511_01
Revises: 20260502_01
Create Date: 2026-05-11 15:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260511_01"
down_revision: Union[str, Sequence[str], None] = "20260502_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "prompts" not in _existing_tables():
        return

    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS skill_markdown TEXT NOT NULL DEFAULT ''
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS skill_python_script TEXT NOT NULL DEFAULT ''
        """
    )
    op.execute(
        """
        UPDATE prompts
           SET skill_markdown = COALESCE(skill_markdown, ''),
               skill_python_script = COALESCE(skill_python_script, '')
        """
    )


def downgrade() -> None:
    if "prompts" not in _existing_tables():
        return

    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS skill_python_script
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS skill_markdown
        """
    )
