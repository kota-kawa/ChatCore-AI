"""Add OAuth persistence for the remote MCP server.

Revision ID: 20260713_01
Revises: 20260710_02
Create Date: 2026-07-13 12:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260713_01"
down_revision: Union[str, Sequence[str], None] = "20260710_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
            client_id TEXT PRIMARY KEY,
            metadata JSONB NOT NULL,
            client_secret_encrypted TEXT NULL,
            registration_method VARCHAR(16) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMPTZ NULL,
            CHECK (registration_method IN ('dcr', 'cimd', 'pre_registered'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_oauth_grants (
            id UUID PRIMARY KEY,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_id TEXT NOT NULL,
            client_name VARCHAR(255) NOT NULL,
            client_host VARCHAR(255) NOT NULL,
            scopes TEXT[] NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMPTZ NULL,
            revoked_at TIMESTAMPTZ NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mcp_oauth_grants_active_user
            ON mcp_oauth_grants (user_id, created_at DESC)
            WHERE revoked_at IS NULL
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_oauth_authorization_codes (
            code_digest CHAR(64) PRIMARY KEY,
            grant_id UUID NOT NULL REFERENCES mcp_oauth_grants(id) ON DELETE CASCADE,
            client_id TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            code_challenge TEXT NOT NULL,
            scopes TEXT[] NOT NULL,
            resource TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mcp_oauth_codes_expiry
            ON mcp_oauth_authorization_codes (expires_at)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_oauth_tokens (
            token_digest CHAR(64) PRIMARY KEY,
            grant_id UUID NOT NULL REFERENCES mcp_oauth_grants(id) ON DELETE CASCADE,
            client_id TEXT NOT NULL,
            token_type VARCHAR(16) NOT NULL,
            scopes TEXT[] NOT NULL,
            resource TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ NULL,
            replaced_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMPTZ NULL,
            CHECK (token_type IN ('access', 'refresh'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mcp_oauth_tokens_active_grant
            ON mcp_oauth_tokens (grant_id, token_type, expires_at)
            WHERE revoked_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mcp_oauth_tokens")
    op.execute("DROP TABLE IF EXISTS mcp_oauth_authorization_codes")
    op.execute("DROP TABLE IF EXISTS mcp_oauth_grants")
    op.execute("DROP TABLE IF EXISTS mcp_oauth_clients")
