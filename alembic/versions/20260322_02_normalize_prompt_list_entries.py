"""Normalize prompt_list_entries to reference prompts only.

Revision ID: 20260322_02
Revises: 20260322_01
Create Date: 2026-03-22 14:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260322_02"
down_revision: Union[str, Sequence[str], None] = "20260322_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    tables = _existing_tables()
    if "prompt_list_entries" not in tables or "prompts" not in tables or "users" not in tables:
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_list_entries_v2 (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            prompt_id INT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_prompt_list_v2_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_prompt_list_v2_prompt
                FOREIGN KEY (prompt_id)
                REFERENCES prompts(id)
                ON DELETE CASCADE,
            CONSTRAINT uq_prompt_list_v2_user_prompt
                UNIQUE (user_id, prompt_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_list_v2_user_created_at
            ON prompt_list_entries_v2 (user_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        WITH resolved_entries AS (
            SELECT ple.id,
                   ple.user_id,
                   COALESCE(ple.prompt_id, matched.prompt_id) AS resolved_prompt_id,
                   ple.created_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY ple.user_id, COALESCE(ple.prompt_id, matched.prompt_id)
                       ORDER BY ple.created_at DESC, ple.id DESC
                   ) AS row_num
            FROM prompt_list_entries ple
            LEFT JOIN LATERAL (
                SELECT p.id AS prompt_id
                FROM prompts p
                WHERE p.title = ple.title
                  AND p.content = ple.content
                  AND COALESCE(p.category, '') = COALESCE(ple.category, '')
                  AND COALESCE(p.input_examples, '') = COALESCE(ple.input_examples, '')
                  AND COALESCE(p.output_examples, '') = COALESCE(ple.output_examples, '')
                ORDER BY p.id DESC
                LIMIT 1
            ) matched ON TRUE
            WHERE COALESCE(ple.prompt_id, matched.prompt_id) IS NOT NULL
        )
        INSERT INTO prompt_list_entries_v2 (user_id, prompt_id, created_at)
        SELECT user_id, resolved_prompt_id, created_at
        FROM resolved_entries
        WHERE row_num = 1
        ORDER BY created_at, id
        """
    )
    op.execute("DROP TABLE IF EXISTS prompt_list_entries")
    op.execute("ALTER TABLE prompt_list_entries_v2 RENAME TO prompt_list_entries")
    op.execute(
        """
        ALTER INDEX IF EXISTS idx_prompt_list_v2_user_created_at
        RENAME TO idx_prompt_list_user_created_at
        """
    )
    op.execute(
        """
        ALTER TABLE prompt_list_entries
            RENAME CONSTRAINT fk_prompt_list_v2_user TO fk_prompt_list_user
        """
    )
    op.execute(
        """
        ALTER TABLE prompt_list_entries
            RENAME CONSTRAINT fk_prompt_list_v2_prompt TO fk_prompt_list_prompt
        """
    )
    op.execute(
        """
        ALTER TABLE prompt_list_entries
            RENAME CONSTRAINT uq_prompt_list_v2_user_prompt TO uq_prompt_list_user_prompt
        """
    )


def downgrade() -> None:
    tables = _existing_tables()
    if "prompt_list_entries" not in tables or "prompts" not in tables or "users" not in tables:
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_list_entries_legacy (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            prompt_id INT NULL,
            title VARCHAR(255) NOT NULL,
            category VARCHAR(50) DEFAULT '',
            content TEXT NOT NULL,
            input_examples TEXT,
            output_examples TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_prompt_list_legacy_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_prompt_list_legacy_prompt
                FOREIGN KEY (prompt_id)
                REFERENCES prompts(id)
                ON DELETE SET NULL,
            CONSTRAINT uq_prompt_list_legacy_user_prompt
                UNIQUE (user_id, prompt_id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO prompt_list_entries_legacy
            (user_id, prompt_id, title, category, content, input_examples, output_examples, created_at)
        SELECT ple.user_id,
               ple.prompt_id,
               p.title,
               p.category,
               p.content,
               p.input_examples,
               p.output_examples,
               ple.created_at
        FROM prompt_list_entries ple
        JOIN prompts p ON p.id = ple.prompt_id
        ORDER BY ple.created_at, ple.id
        """
    )
    op.execute("DROP TABLE IF EXISTS prompt_list_entries")
    op.execute("ALTER TABLE prompt_list_entries_legacy RENAME TO prompt_list_entries")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_list_user_title
            ON prompt_list_entries (user_id, title)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_list_user_created_at
            ON prompt_list_entries (user_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = 'uq_prompt_list_user_title_when_prompt_null'
            ) THEN
                CREATE UNIQUE INDEX uq_prompt_list_user_title_when_prompt_null
                    ON prompt_list_entries (user_id, title)
                    WHERE prompt_id IS NULL;
            END IF;
        END $$;
        """
    )
