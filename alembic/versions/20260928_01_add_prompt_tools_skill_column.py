"""Add the built-in "Prompt sharing and settings" Skill preference.

Revision ID: 20260928_01
Revises: 20260924_03
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_01"
down_revision: Union[str, Sequence[str], None] = "20260924_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 追加のみ: 既定スキル「プロンプト共有と設定」の ON/OFF。新規・既存ユーザーとも ON で始める
    # （既定スキル「メモ」20260924_03 と同じ方式）。
    # Expand only: the on/off state of the built-in "Prompt sharing and settings" Skill, on for
    # new and existing users (same approach as the built-in "Memo" Skill in 20260924_03).
    op.add_column(
        "users",
        sa.Column(
            "prompt_tools_skill_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "20260928_01 is intentionally irreversible: dropping this column would discard every "
        "user's Prompt sharing and settings Skill preference."
    )
