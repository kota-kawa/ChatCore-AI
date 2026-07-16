"""Prepare stable cursor pagination for the public prompt feed.

Revision ID: 20260716_01
Revises: 20260714_03
Create Date: 2026-07-16 12:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260716_01"
down_revision: Union[str, Sequence[str], None] = "20260714_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # カーソルキーを全行で必ず生成できるよう、既存NULLを補正して制約を付ける。
    op.execute("UPDATE prompts SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("ALTER TABLE prompts ALTER COLUMN created_at SET NOT NULL")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_active_public_created_at_id
            ON prompts (created_at DESC, id DESC)
            WHERE is_public = TRUE AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_prompts_active_public_created_at_id")
    op.execute("ALTER TABLE prompts ALTER COLUMN created_at DROP NOT NULL")
