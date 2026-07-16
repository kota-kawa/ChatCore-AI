"""Reauthorize legacy prompt-only MCP connections.

Revision ID: 20260716_03
Revises: 20260716_02
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260716_03"
down_revision: Union[str, Sequence[str], None] = "20260716_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ALL_SCOPES = "prompts:read prompts:write memos:read memos:write"


def upgrade() -> None:
    """Mark old grants and allow their clients to request the new tool scopes."""
    # The default stays at version 1 so the old app in a blue/green deployment
    # cannot create a current-generation grant after this migration runs. The
    # new app writes version 2 explicitly and lazily rejects version 1 tokens.
    op.execute(
        """
        ALTER TABLE mcp_oauth_grants
        ADD COLUMN IF NOT EXISTS scope_version SMALLINT NOT NULL DEFAULT 1
        """
    )
    op.execute(
        """
        UPDATE mcp_oauth_grants
        SET scope_version = 2
        WHERE scopes <> ARRAY['prompts:write']::text[]
        """
    )

    # Expanding client registration metadata only allows the client to ask for
    # these scopes. User grants and tokens remain separate and are not widened.
    op.execute(
        f"""
        UPDATE mcp_oauth_clients
        SET metadata = jsonb_set(metadata, '{{scope}}', to_jsonb('{_ALL_SCOPES}'::text), true)
        WHERE metadata ->> 'scope' = 'prompts:write'
        """
    )



def downgrade() -> None:
    """Remove the grant generation marker."""
    op.execute("ALTER TABLE mcp_oauth_grants DROP COLUMN IF EXISTS scope_version")
