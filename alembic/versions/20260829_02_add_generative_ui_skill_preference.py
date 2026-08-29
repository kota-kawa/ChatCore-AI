"""Add the per-user Generative UI system Skill preference.

Revision ID: 20260829_02
Revises: 20260829_01
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260829_02"
down_revision: Union[str, Sequence[str], None] = "20260829_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "generative_ui_skill_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "20260829_02 is intentionally irreversible: removing the column would discard "
        "each user's Generative UI Skill preference."
    )
