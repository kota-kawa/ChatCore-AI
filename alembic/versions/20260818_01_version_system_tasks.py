"""Version system tasks without changing existing users.

Revision ID: 20260818_01
Revises: 20260809_01
Create Date: 2026-08-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260818_01"
down_revision: Union[str, Sequence[str], None] = "20260809_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_with_examples",
        sa.Column(
            "system_task_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )

    # Existing user-owned tasks stay on revision 1. Only the shared catalog used
    # by guests and copied to new users advances to the current revision.
    op.execute(
        """
        UPDATE task_with_examples
           SET system_task_revision = 2
         WHERE user_id IS NULL
           AND system_task_key IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("task_with_examples", "system_task_revision")
