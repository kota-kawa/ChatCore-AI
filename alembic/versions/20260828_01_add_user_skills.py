"""Add user-owned reusable chat skills.

Revision ID: 20260828_01
Revises: 20260826_01
Create Date: 2026-08-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260828_01"
down_revision: Union[str, Sequence[str], None] = "20260826_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_skills",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("TRUE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 100",
            name="chk_user_skills_name_length",
        ),
        sa.CheckConstraint(
            "char_length(btrim(instructions)) BETWEEN 1 AND 12000",
            name="chk_user_skills_instructions_length",
        ),
    )
    op.create_index(
        "idx_user_skills_user_created_at",
        "user_skills",
        ["user_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "idx_user_skills_user_enabled",
        "user_skills",
        ["user_id", "is_enabled", "id"],
        unique=False,
    )
    op.create_index(
        "uq_user_skills_user_normalized_name",
        "user_skills",
        ["user_id", sa.text("lower(btrim(name))")],
        unique=True,
    )


def downgrade() -> None:
    raise RuntimeError(
        "20260828_01 is intentionally irreversible: back up and perform a reviewed "
        "contract migration before removing user-owned skills."
    )
