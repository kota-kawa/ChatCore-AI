"""Add user-managed display names to MCP OAuth connections.

Revision ID: 20260714_03
Revises: 20260714_02
Create Date: 2026-07-14 15:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260714_03"
down_revision: Union[str, Sequence[str], None] = "20260714_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # OAuthクライアントが申告した client_name は監査情報として維持し、
    # ユーザーが一覧で使う別名だけを別カラムへ保存する。
    op.execute(
        "ALTER TABLE mcp_oauth_grants "
        "ADD COLUMN IF NOT EXISTS display_name VARCHAR(100) NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE mcp_oauth_grants DROP COLUMN IF EXISTS display_name")
