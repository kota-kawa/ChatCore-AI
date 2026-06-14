"""Backfill prompt bookmarks from task copies.

Revision ID: 20260517_01
Revises: 20260515_01
Create Date: 2026-05-17 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260517_01"
down_revision: Union[str, Sequence[str], None] = "20260515_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        WITH matched_task_bookmarks AS (
            SELECT
                t.user_id,
                p.id AS prompt_id,
                t.created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY t.user_id, p.id
                    ORDER BY t.created_at ASC, t.id ASC
                ) AS row_num
            FROM task_with_examples AS t
            JOIN prompts AS p
              ON p.title = t.name
             AND p.content = t.prompt_template
             AND COALESCE(p.input_examples, '') = COALESCE(t.input_examples, '')
             AND COALESCE(p.output_examples, '') = COALESCE(t.output_examples, '')
             AND p.is_public = TRUE
             AND p.deleted_at IS NULL
            WHERE t.user_id IS NOT NULL
              AND t.deleted_at IS NULL
        )
        INSERT INTO prompt_list_entries (user_id, prompt_id, created_at)
        SELECT user_id, prompt_id, created_at
        FROM matched_task_bookmarks
        WHERE row_num = 1
        ON CONFLICT (user_id, prompt_id) DO NOTHING
        """
    )


def downgrade() -> None:
    pass
