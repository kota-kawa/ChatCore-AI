"""Add normalized resources for shared SKILL posts.

Revision ID: 20260724_01
Revises: 20260723_01
Create Date: 2026-07-24
"""

from __future__ import annotations

import hashlib
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_01"
down_revision: Union[str, Sequence[str], None] = "20260723_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """Create prompt_resources and migrate the legacy Python resource."""
    if "prompts" not in _existing_tables():
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_resources (
            id BIGSERIAL PRIMARY KEY,
            prompt_id INTEGER NOT NULL,
            path VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL,
            language VARCHAR(64) NOT NULL DEFAULT 'text',
            media_type VARCHAR(128) NOT NULL DEFAULT 'text/plain',
            text_content TEXT NULL,
            storage_key VARCHAR(1024) NULL,
            size_bytes BIGINT NOT NULL DEFAULT 0,
            sha256 CHAR(64) NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_prompt_resources_prompt
                FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
            CONSTRAINT uq_prompt_resources_prompt_path UNIQUE (prompt_id, path),
            CONSTRAINT ck_prompt_resources_role
                CHECK (role IN ('script', 'reference', 'config', 'other')),
            CONSTRAINT ck_prompt_resources_content_location
                CHECK ((text_content IS NOT NULL) <> (storage_key IS NOT NULL)),
            CONSTRAINT ck_prompt_resources_size
                CHECK (size_bytes >= 0),
            CONSTRAINT ck_prompt_resources_sha256
                CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_resources_prompt_lower_path
            ON prompt_resources (prompt_id, lower(path))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_resources_prompt_order
            ON prompt_resources (prompt_id, sort_order, id)
        """
    )

    # Compute the digest in Python so the migration does not require pgcrypto.
    bind = op.get_bind()
    legacy_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id, attributes->>'skill_python_script' AS content
                FROM prompts
                WHERE content_format = 'skill'
                  AND COALESCE(attributes->>'skill_python_script', '') <> ''
                """
            )
        ).mappings()
    )
    insert_resource = sa.text(
        """
        INSERT INTO prompt_resources (
            prompt_id, path, role, language, media_type, text_content,
            storage_key, size_bytes, sha256, sort_order, created_at, updated_at
        )
        VALUES (
            :prompt_id, 'scripts/main.py', 'script', 'python', 'text/x-python',
            :content, NULL, :size_bytes, :sha256, 0, NOW(), NOW()
        )
        ON CONFLICT (prompt_id, path) DO NOTHING
        """
    )
    for row in legacy_rows:
        content = str(row["content"] or "")
        encoded = content.encode("utf-8")
        bind.execute(
            insert_resource,
            {
                "prompt_id": int(row["id"]),
                "content": content,
                "size_bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            },
        )


def downgrade() -> None:
    """Restore the legacy Python attribute and remove normalized resources."""
    if "prompt_resources" not in _existing_tables():
        return

    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text(
                """
                SELECT prompt_id, text_content
                FROM prompt_resources
                WHERE lower(path) = 'scripts/main.py'
                  AND text_content IS NOT NULL
                """
            )
        ).mappings()
    )
    restore_legacy = sa.text(
        """
        UPDATE prompts
        SET attributes = jsonb_set(
            COALESCE(attributes, '{}'::jsonb),
            '{skill_python_script}',
            to_jsonb(CAST(:content AS TEXT)),
            true
        )
        WHERE id = :prompt_id
        """
    )
    for row in rows:
        bind.execute(
            restore_legacy,
            {
                "prompt_id": int(row["prompt_id"]),
                "content": str(row["text_content"] or ""),
            },
        )

    op.execute("DROP TABLE IF EXISTS prompt_resources")
