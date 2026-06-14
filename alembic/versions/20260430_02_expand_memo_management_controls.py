"""Expand memo management and share lifecycle controls.

Revision ID: 20260430_02
Revises: 20260430_01
Create Date: 2026-04-30 13:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260430_02"
down_revision: Union[str, Sequence[str], None] = "20260430_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    # Check existing tables in the database schema.
    # データベースのスキーマ内に存在するテーブルを確認します。
    tables = _existing_tables()

    # Expand memo_entries table with archived_at, pinned_at and their index.
    # memo_entriesテーブルを拡張し、archived_at、pinned_at列およびインデックスを追加します。
    if "memo_entries" in tables:
        op.execute("ALTER TABLE memo_entries ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
        op.execute("ALTER TABLE memo_entries ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMP NULL")
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memo_entries_user_archived_pinned_created
                ON memo_entries (user_id, archived_at, pinned_at DESC, created_at DESC)
            """
        )

    # Expand shared_memo_entries table with expires_at, revoked_at and their index.
    # shared_memo_entriesテーブルを拡張し、expires_at、revoked_at列およびインデックスを追加します。
    if "shared_memo_entries" in tables:
        op.execute("ALTER TABLE shared_memo_entries ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP NULL")
        op.execute("ALTER TABLE shared_memo_entries ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMP NULL")
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_shared_memo_entries_active_lookup
                ON shared_memo_entries (memo_entry_id, revoked_at, expires_at)
            """
        )


def downgrade() -> None:
    # Drop index on shared_memo_entries.
    # shared_memo_entriesのインデックスを削除します。
    op.execute("DROP INDEX IF EXISTS idx_shared_memo_entries_active_lookup")
    # Drop index on memo_entries.
    # memo_entriesのインデックスを削除します。
    op.execute("DROP INDEX IF EXISTS idx_memo_entries_user_archived_pinned_created")
    # Drop revoked_at and expires_at columns from shared_memo_entries.
    # shared_memo_entriesテーブルからrevoked_atおよびexpires_at列を削除します。
    op.execute("ALTER TABLE shared_memo_entries DROP COLUMN IF EXISTS revoked_at")
    op.execute("ALTER TABLE shared_memo_entries DROP COLUMN IF EXISTS expires_at")
    # Drop pinned_at and archived_at columns from memo_entries.
    # memo_entriesテーブルからpinned_atおよびarchived_at列を削除します。
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS pinned_at")
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS archived_at")
