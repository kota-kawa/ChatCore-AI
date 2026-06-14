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
    tables = _existing_tables()

    if "memo_entries" in tables:
        op.execute("ALTER TABLE memo_entries ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
        op.execute("ALTER TABLE memo_entries ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMP NULL")
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memo_entries_user_archived_pinned_created
                ON memo_entries (user_id, archived_at, pinned_at DESC, created_at DESC)
            """
        )

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
    op.execute("DROP INDEX IF EXISTS idx_shared_memo_entries_active_lookup")
    op.execute("DROP INDEX IF EXISTS idx_memo_entries_user_archived_pinned_created")
    op.execute("ALTER TABLE shared_memo_entries DROP COLUMN IF EXISTS revoked_at")
    op.execute("ALTER TABLE shared_memo_entries DROP COLUMN IF EXISTS expires_at")
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS pinned_at")
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS archived_at")
