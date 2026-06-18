"""Add source prompt tracking to task templates.

Revision ID: 20260618_02
Revises: 20260618_01
Create Date: 2026-06-18
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260618_02"
down_revision: Union[str, Sequence[str], None] = "20260618_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a nullable source prompt reference for use-in-chat state."""
    op.execute(
        """
        ALTER TABLE task_with_examples
        ADD COLUMN IF NOT EXISTS source_prompt_id INTEGER
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                  FROM pg_constraint
                 WHERE conname = 'fk_task_with_examples_source_prompt'
            ) THEN
                ALTER TABLE task_with_examples
                ADD CONSTRAINT fk_task_with_examples_source_prompt
                FOREIGN KEY (source_prompt_id)
                REFERENCES prompts(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_with_examples_active_user_source_prompt
            ON task_with_examples (user_id, source_prompt_id)
            WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    """Remove the source prompt reference from task templates."""
    op.execute("DROP INDEX IF EXISTS idx_task_with_examples_active_user_source_prompt")
    op.execute(
        """
        ALTER TABLE task_with_examples
        DROP CONSTRAINT IF EXISTS fk_task_with_examples_source_prompt
        """
    )
    op.execute(
        """
        ALTER TABLE task_with_examples
        DROP COLUMN IF EXISTS source_prompt_id
        """
    )
