"""Merge chat branching and memo visual migration heads.

Revision ID: 20260524_02
Revises: 20260520_01, 20260524_01
Create Date: 2026-05-24 12:30:00
"""

from typing import Sequence, Union

revision: str = "20260524_02"
down_revision: Union[str, Sequence[str], None] = ("20260520_01", "20260524_01")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
