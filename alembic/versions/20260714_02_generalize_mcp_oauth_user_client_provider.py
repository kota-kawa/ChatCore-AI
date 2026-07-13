"""Allow manually issued MCP OAuth clients for arbitrary AI services.

Revision ID: 20260714_02
Revises: 20260714_01
Create Date: 2026-07-14 10:30:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260714_02"
down_revision: Union[str, Sequence[str], None] = "20260714_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE mcp_oauth_user_clients "
        "DROP CONSTRAINT IF EXISTS mcp_oauth_user_clients_provider_check"
    )
    op.execute(
        """
        ALTER TABLE mcp_oauth_user_clients
        ADD CONSTRAINT mcp_oauth_user_clients_provider_check
        CHECK (provider IN ('claude', 'manual'))
        """
    )


def downgrade() -> None:
    op.execute("UPDATE mcp_oauth_user_clients SET provider = 'claude' WHERE provider = 'manual'")
    op.execute(
        "ALTER TABLE mcp_oauth_user_clients "
        "DROP CONSTRAINT IF EXISTS mcp_oauth_user_clients_provider_check"
    )
    op.execute(
        """
        ALTER TABLE mcp_oauth_user_clients
        ADD CONSTRAINT mcp_oauth_user_clients_provider_check
        CHECK (provider IN ('claude'))
        """
    )
