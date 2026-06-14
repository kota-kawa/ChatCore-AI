"""Add memo collections, embedding column, and semantic search support.

Revision ID: 20260501_01
Revises: 20260430_02
Create Date: 2026-05-01 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260501_01"
down_revision: Union[str, Sequence[str], None] = "20260430_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    tables = _existing_tables()

    if "memo_collections" not in tables:
        op.execute(
            """
            CREATE TABLE memo_collections (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                name VARCHAR(100) NOT NULL,
                color VARCHAR(20) NOT NULL DEFAULT '#6b7280',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_memo_collections_user
                    FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE,
                UNIQUE (user_id, name)
            )
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memo_collections_user_created
                ON memo_collections (user_id, created_at DESC)
            """
        )
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'trg_memo_collections_updated_at'
                      AND tgrelid = 'memo_collections'::regclass
                ) THEN
                    CREATE TRIGGER trg_memo_collections_updated_at
                    BEFORE UPDATE ON memo_collections
                    FOR EACH ROW
                    EXECUTE FUNCTION set_updated_at();
                END IF;
            END $$;
            """
        )

    if "memo_entries" in tables:
        op.execute(
            """
            ALTER TABLE memo_entries
                ADD COLUMN IF NOT EXISTS collection_id INT NULL,
                ADD COLUMN IF NOT EXISTS embedding TEXT NULL
            """
        )
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'fk_memo_entries_collection'
                      AND table_name = 'memo_entries'
                ) THEN
                    ALTER TABLE memo_entries
                    ADD CONSTRAINT fk_memo_entries_collection
                    FOREIGN KEY (collection_id)
                    REFERENCES memo_collections(id)
                    ON DELETE SET NULL;
                END IF;
            END $$;
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memo_entries_collection_id
                ON memo_entries (user_id, collection_id)
                WHERE collection_id IS NOT NULL
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memo_entries_has_embedding
                ON memo_entries (user_id, created_at DESC)
                WHERE embedding IS NOT NULL
            """
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memo_entries_has_embedding")
    op.execute("DROP INDEX IF EXISTS idx_memo_entries_collection_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_memo_entries_collection'
                  AND table_name = 'memo_entries'
            ) THEN
                ALTER TABLE memo_entries DROP CONSTRAINT fk_memo_entries_collection;
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS collection_id")
    op.execute("DROP TRIGGER IF EXISTS trg_memo_collections_updated_at ON memo_collections")
    op.execute("DROP INDEX IF EXISTS idx_memo_collections_user_created")
    op.execute("DROP TABLE IF EXISTS memo_collections")
