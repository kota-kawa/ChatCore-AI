"""Allow one cookie- and IP-limited guest prompt to be claimed after sign-up.

Revision ID: 20260824_01
Revises: 20260818_01
Create Date: 2026-08-24
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260824_01"
down_revision: Union[str, Sequence[str], None] = "20260818_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow anonymous prompt ownership and record only hashed quota identities."""
    op.execute("ALTER TABLE prompts ALTER COLUMN user_id DROP NOT NULL")
    op.execute(
        """
        CREATE TABLE guest_prompt_submissions (
            id BIGSERIAL PRIMARY KEY,
            prompt_id INTEGER NOT NULL UNIQUE,
            guest_cookie_hash CHAR(64) NOT NULL,
            client_ip_hash CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            claimed_by_user_id INTEGER NULL,
            claimed_at TIMESTAMPTZ NULL,
            CONSTRAINT fk_guest_prompt_submissions_prompt
                FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
            CONSTRAINT fk_guest_prompt_submissions_claimed_by
                FOREIGN KEY (claimed_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT ck_guest_prompt_submissions_claimed_at
                CHECK (
                    claimed_at IS NULL OR claimed_by_user_id IS NOT NULL
                )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_guest_prompt_submissions_cookie_created_at
            ON guest_prompt_submissions (guest_cookie_hash, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_guest_prompt_submissions_ip_created_at
            ON guest_prompt_submissions (client_ip_hash, created_at DESC)
        """
    )


def downgrade() -> None:
    """Remove anonymous prompts before restoring the original ownership constraint."""
    op.execute(
        """
        DELETE FROM prompts AS p
        USING guest_prompt_submissions AS gps
        WHERE gps.prompt_id = p.id
          AND p.user_id IS NULL
        """
    )
    op.execute("DROP TABLE guest_prompt_submissions")
    op.execute("ALTER TABLE prompts ALTER COLUMN user_id SET NOT NULL")
