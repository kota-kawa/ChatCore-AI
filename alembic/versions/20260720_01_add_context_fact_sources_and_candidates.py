"""Add context fact provenance, idempotency, and review candidates.

Revision ID: 20260720_01
Revises: 20260719_01
Create Date: 2026-07-20
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260720_01"
down_revision: Union[str, Sequence[str], None] = "20260719_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add fact provenance and a separate review queue for extracted facts."""
    op.execute(
        """
        ALTER TABLE context_facts
            ADD COLUMN source_kind VARCHAR(20) NOT NULL DEFAULT 'manual',
            ADD COLUMN source_ref VARCHAR(500),
            ADD COLUMN source_client_id TEXT,
            ADD COLUMN importance SMALLINT NOT NULL DEFAULT 50,
            ADD COLUMN idempotency_key_hash CHAR(64),
            ADD COLUMN idempotency_payload_hash CHAR(64),
            ADD CONSTRAINT ck_context_facts_source_kind
                CHECK (source_kind IN ('manual', 'mcp', 'chat', 'import')),
            ADD CONSTRAINT ck_context_facts_importance
                CHECK (importance BETWEEN 0 AND 100),
            ADD CONSTRAINT ck_context_facts_idempotency_key_hash
                CHECK (
                    idempotency_key_hash IS NULL
                    OR idempotency_key_hash ~ '^[0-9a-f]{64}$'
                ),
            ADD CONSTRAINT ck_context_facts_idempotency_payload_hash
                CHECK (
                    idempotency_payload_hash IS NULL
                    OR idempotency_payload_hash ~ '^[0-9a-f]{64}$'
                ),
            ADD CONSTRAINT ck_context_facts_idempotency_hash_pair
                CHECK (
                    (idempotency_key_hash IS NULL) =
                    (idempotency_payload_hash IS NULL)
                ),
            ADD CONSTRAINT uq_context_facts_idempotency_key_hash
                UNIQUE (idempotency_key_hash)
        """
    )

    op.execute(
        """
        CREATE TABLE context_fact_candidates (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            fact_type VARCHAR(20) NOT NULL
                CHECK (fact_type IN ('preference', 'profile', 'project', 'decision', 'reference')),
            title VARCHAR(100) NOT NULL CHECK (char_length(title) >= 1),
            content TEXT NOT NULL CHECK (char_length(content) BETWEEN 1 AND 2000),
            source_kind VARCHAR(20) NOT NULL DEFAULT 'chat'
                CHECK (source_kind IN ('manual', 'mcp', 'chat', 'import')),
            source_ref VARCHAR(500),
            source_client_id TEXT,
            importance SMALLINT NOT NULL DEFAULT 50
                CHECK (importance BETWEEN 0 AND 100),
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0
                CHECK (confidence BETWEEN 0 AND 1),
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
            fingerprint CHAR(64) NOT NULL
                CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
            promoted_fact_id INTEGER REFERENCES context_facts(id) ON DELETE SET NULL,
            revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_context_fact_candidates_updated_at
        BEFORE UPDATE ON context_fact_candidates
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at()
        """
    )

    # Keep the migration atomic. context_facts is capped at 200 active rows per
    # user and the candidate table is new, so regular index creation is a safer
    # tradeoff than leaving partially applied DDL around after a CONCURRENTLY
    # failure.
    op.execute(
        """
        CREATE INDEX idx_context_facts_user_digest
            ON context_facts (
                user_id,
                status,
                importance DESC,
                updated_at DESC,
                id DESC
            )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_context_fact_candidates_user_status
            ON context_fact_candidates (user_id, status, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_context_fact_candidates_pending_fingerprint
            ON context_fact_candidates (user_id, fingerprint)
            WHERE status = 'pending'
        """
    )
    op.execute(
        """
        CREATE INDEX idx_context_fact_candidates_promoted_fact
            ON context_fact_candidates (promoted_fact_id)
            WHERE promoted_fact_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Remove the review queue and fact provenance fields."""
    op.execute("DROP INDEX IF EXISTS idx_context_fact_candidates_promoted_fact")
    op.execute("DROP INDEX IF EXISTS uq_context_fact_candidates_pending_fingerprint")
    op.execute("DROP INDEX IF EXISTS idx_context_fact_candidates_user_status")
    op.execute("DROP INDEX IF EXISTS idx_context_facts_user_digest")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_context_fact_candidates_updated_at "
        "ON context_fact_candidates"
    )
    op.execute("DROP TABLE context_fact_candidates")
    op.execute(
        """
        ALTER TABLE context_facts
            DROP COLUMN idempotency_payload_hash,
            DROP COLUMN idempotency_key_hash,
            DROP COLUMN importance,
            DROP COLUMN source_client_id,
            DROP COLUMN source_ref,
            DROP COLUMN source_kind
        """
    )
