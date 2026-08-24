"""Track public prompt detail views outside prompt revision history.

Revision ID: 20260824_02
Revises: 20260824_01
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260824_02"
down_revision: Union[str, Sequence[str], None] = "20260824_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create an atomic counter that does not trigger prompt edit history."""
    op.execute(
        """
        CREATE TABLE prompt_view_counts (
            prompt_id INTEGER PRIMARY KEY,
            view_count BIGINT NOT NULL DEFAULT 0,
            CONSTRAINT fk_prompt_view_counts_prompt
                FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
            CONSTRAINT ck_prompt_view_counts_non_negative
                CHECK (view_count >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_prompt_view_counts_popular
            ON prompt_view_counts (view_count DESC, prompt_id DESC)
        """
    )


def downgrade() -> None:
    """Remove prompt view counters."""
    op.execute("DROP TABLE prompt_view_counts")
