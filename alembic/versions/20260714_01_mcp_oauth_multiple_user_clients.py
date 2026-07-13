"""Allow multiple named personal MCP OAuth clients per user.

Revision ID: 20260714_01
Revises: 20260713_02
Create Date: 2026-07-14 09:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260714_01"
down_revision: Union[str, Sequence[str], None] = "20260713_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ユーザーごとに複数の認証情報（APIキーのような使い方）を保存できるように、
    # provider 単位で1件に制限していた部分ユニークインデックスを削除する。
    # Drop the per-provider uniqueness so a user can keep several credentials at once.
    op.execute("DROP INDEX IF EXISTS uq_mcp_oauth_user_clients_active_provider")
    # 認証情報に用途名（ラベル）を付けられるようにする。
    # Let each credential carry an optional human-readable label.
    op.execute("ALTER TABLE mcp_oauth_user_clients ADD COLUMN IF NOT EXISTS label VARCHAR(100) NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE mcp_oauth_user_clients DROP COLUMN IF EXISTS label")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_oauth_user_clients_active_provider
            ON mcp_oauth_user_clients (user_id, provider)
            WHERE revoked_at IS NULL
        """
    )
