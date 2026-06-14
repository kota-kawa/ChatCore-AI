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


# 日本語: upgrade のスキーマ更新処理を担当します。
# English: Handle upgrading schema for upgrade.
def upgrade() -> None:
    pass


# 日本語: downgrade のスキーマ差し戻し処理を担当します。
# English: Handle downgrading schema for downgrade.
def downgrade() -> None:
    pass
