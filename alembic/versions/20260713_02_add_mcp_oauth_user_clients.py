"""Add ownership records for personal MCP OAuth clients.

Revision ID: 20260713_02
Revises: 20260713_01
Create Date: 2026-07-13 18:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260713_02"
down_revision: Union[str, Sequence[str], None] = "20260713_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE mcp_oauth_user_clients (
            client_id TEXT PRIMARY KEY REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(32) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            revoked_at TIMESTAMPTZ NULL,
            CHECK (provider IN ('claude'))
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_mcp_oauth_user_clients_active_provider
            ON mcp_oauth_user_clients (user_id, provider)
            WHERE revoked_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE mcp_oauth_user_clients")
