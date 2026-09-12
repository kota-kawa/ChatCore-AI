"""Add revocation and expiry columns to chat share links.

Revision ID: 20260913_01
Revises: 20260901_01
Create Date: 2026-09-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260913_01"
down_revision: Union[str, Sequence[str], None] = "20260901_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Expand only: both columns are nullable, so a previous Blue/Green color that
    # never selects them keeps serving shared chat links while this runs.
    # 追加のみ: どちらも NULL 許容のため、この列を読まない旧バージョンが動いていても
    # 共有チャットの閲覧は壊れません。
    op.add_column(
        "shared_chat_rooms",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "shared_chat_rooms",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shared_chat_rooms", "revoked_at")
    op.drop_column("shared_chat_rooms", "expires_at")
