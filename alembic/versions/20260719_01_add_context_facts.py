"""Add personal context vault (context_facts) and widen MCP client scopes.

Revision ID: 20260719_01
Revises: 20260716_03
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260719_01"
down_revision: Union[str, Sequence[str], None] = "20260716_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Existing full scope set granted to current-generation clients (see 20260716_03),
# and the widened set that also includes the personal context vault scopes.
_CURRENT_SCOPES = "prompts:read prompts:write memos:read memos:write"
_WIDENED_SCOPES = (
    "prompts:read prompts:write memos:read memos:write context:read context:write"
)


def upgrade() -> None:
    """Create the context_facts table and allow existing clients to request context scopes."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS context_facts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            fact_type VARCHAR(20) NOT NULL
                CHECK (fact_type IN ('preference', 'profile', 'project', 'decision', 'reference')),
            title VARCHAR(100) NOT NULL CHECK (char_length(title) >= 1),
            content TEXT NOT NULL CHECK (char_length(content) BETWEEN 1 AND 2000),
            status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'deprecated')),
            revision BIGINT NOT NULL DEFAULT 1,
            embedding_vector vector(768),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Keep updated_at fresh via the shared trigger function created with the memo tables.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger
                WHERE tgname = 'trg_context_facts_updated_at'
                  AND tgrelid = 'context_facts'::regclass
            ) THEN
                CREATE TRIGGER trg_context_facts_updated_at
                BEFORE UPDATE ON context_facts
                FOR EACH ROW
                EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
        """
    )

    # Build the larger indexes without holding a write lock for their full duration.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_context_facts_user_status_type
                ON context_facts (user_id, status, fact_type, updated_at DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_context_facts_user_updated_id
                ON context_facts (user_id, updated_at DESC, id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_context_facts_content_trgm
                ON context_facts USING gin (content gin_trgm_ops)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_context_facts_embedding_hnsw
                ON context_facts USING hnsw (embedding_vector vector_cosine_ops)
                WHERE embedding_vector IS NOT NULL
            """
        )

    # Widening client registration metadata only lets a client ask for the new scopes.
    # User grants and tokens remain separate and are never broadened here; the owner
    # must still re-consent before any grant contains context:read/context:write.
    op.execute(
        f"""
        UPDATE mcp_oauth_clients
        SET metadata = jsonb_set(metadata, '{{scope}}', to_jsonb('{_WIDENED_SCOPES}'::text), true)
        WHERE metadata ->> 'scope' = '{_CURRENT_SCOPES}'
        """
    )


def downgrade() -> None:
    """Drop the context_facts table and revert the widened client scope metadata."""
    op.execute(
        f"""
        UPDATE mcp_oauth_clients
        SET metadata = jsonb_set(metadata, '{{scope}}', to_jsonb('{_CURRENT_SCOPES}'::text), true)
        WHERE metadata ->> 'scope' = '{_WIDENED_SCOPES}'
        """
    )

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_context_facts_embedding_hnsw")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_context_facts_content_trgm")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_context_facts_user_updated_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_context_facts_user_status_type")

    op.execute("DROP TRIGGER IF EXISTS trg_context_facts_updated_at ON context_facts")
    op.execute("DROP TABLE IF EXISTS context_facts")
