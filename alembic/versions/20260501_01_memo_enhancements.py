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
    # Check existing tables in the database schema.
    # データベースのスキーマ内に存在するテーブルを確認します。
    tables = _existing_tables()

    # Create memo_collections table and its triggers/indexes if it does not exist.
    # memo_collectionsテーブルが存在しない場合、これを作成しトリガーやインデックスを設定します。
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

    # Expand memo_entries with collection_id, embedding columns and their indexes/constraints.
    # memo_entriesテーブルを拡張し、collection_idおよびembedding列、インデックス、外部キー制約を追加します。
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
    # Drop index idx_memo_entries_has_embedding.
    # インデックス idx_memo_entries_has_embedding を削除します。
    op.execute("DROP INDEX IF EXISTS idx_memo_entries_has_embedding")
    # Drop index idx_memo_entries_collection_id.
    # インデックス idx_memo_entries_collection_id を削除します。
    op.execute("DROP INDEX IF EXISTS idx_memo_entries_collection_id")
    # Drop foreign key constraint fk_memo_entries_collection.
    # 外部キー制約 fk_memo_entries_collection を削除します。
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
    # Drop embedding and collection_id columns from memo_entries table.
    # memo_entriesテーブルからembeddingおよびcollection_id列を削除します。
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS collection_id")
    # Drop update trigger from memo_collections table.
    # memo_collectionsテーブルの更新トリガーを削除します。
    op.execute("DROP TRIGGER IF EXISTS trg_memo_collections_updated_at ON memo_collections")
    # Drop index idx_memo_collections_user_created.
    # インデックス idx_memo_collections_user_created を削除します。
    op.execute("DROP INDEX IF EXISTS idx_memo_collections_user_created")
    # Drop memo_collections table.
    # memo_collectionsテーブルを削除します。
    op.execute("DROP TABLE IF EXISTS memo_collections")
