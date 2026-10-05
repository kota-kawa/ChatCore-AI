"""Add a trash timestamp to memo entries so deleting a memo can be undone.

Revision ID: 20261005_01
Revises: 20260930_01
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261005_01"
down_revision: str | Sequence[str] | None = "20260930_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 追加のみ（expand）。NULL は通常のメモ、値はゴミ箱へ移した日時。旧バージョンは読み書きせず、
    # 旧バージョンの削除は従来どおり物理削除なので、切り替え中に壊れる経路はない。
    # Expand only: NULL is an ordinary memo and a value is when it moved to the trash. The previous
    # color neither reads nor writes it, and its delete stays a physical delete, so nothing breaks
    # while both colors are serving.
    op.execute(
        """
        ALTER TABLE memo_entries
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP
        """
    )
    # 期限切れの一括削除が、ゴミ箱にあるメモだけを走査できるようにする。通常のメモは索引に入らない。
    # Lets the retention purge scan only trashed memos; ordinary memos never enter this index.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memo_entries_deleted_at
                ON memo_entries (deleted_at)
                WHERE deleted_at IS NOT NULL
            """
        )


def downgrade() -> None:
    # ゴミ箱にあるメモは通常のメモとして復活する。削除済みの意図は失われるため、実行前に確認すること。
    # Trashed memos reappear as ordinary memos, losing the intent to delete them; check before running.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_memo_entries_deleted_at")
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS deleted_at")
