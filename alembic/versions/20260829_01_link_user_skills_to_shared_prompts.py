"""Link imported user skills to their shared prompt source.

Revision ID: 20260829_01
Revises: 20260828_01
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260829_01"
down_revision: Union[str, Sequence[str], None] = "20260828_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_skills",
        sa.Column("source_prompt_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_user_skills_source_prompt_id_prompts",
        "user_skills",
        "prompts",
        ["source_prompt_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_user_skills_user_source_prompt",
        "user_skills",
        ["user_id", "source_prompt_id"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "20260829_01 is intentionally irreversible: removing shared-prompt provenance "
        "would prevent imported Skill state from being reconstructed safely."
    )
