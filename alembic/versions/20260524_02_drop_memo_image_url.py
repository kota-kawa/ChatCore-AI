"""Drop memo image URL field.

Revision ID: 20260524_02
Revises: 20260524_01
Create Date: 2026-05-24 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260524_02"
down_revision: Union[str, Sequence[str], None] = "20260524_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS image_url")


def downgrade() -> None:
    op.execute("ALTER TABLE memo_entries ADD COLUMN IF NOT EXISTS image_url VARCHAR(255) NULL")
