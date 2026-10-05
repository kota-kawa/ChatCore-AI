"""Add a trash timestamp to memo entries so deleting a memo can be undone.

Revision ID: 20261005_01
Revises: 20260930_01
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

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
    # ゴミ箱にメモが残っていると、列を落とした時点で利用者が削除したメモが通常のメモとして復活し、
    # 共有を止める目的で消したメモまで一覧や MCP から読めてしまう。データを完全に戻せる保証がない
    # ので、ゴミ箱が空でなければ自動 downgrade を拒否する（20260826_01 と同じ方針）。
    # 空にするには、ゴミ箱を空にする操作か期限切れ削除でメモを物理削除してから実行する。
    # If trashed memos remain, dropping the column would resurrect memos the user deleted as ordinary
    # ones, even ones deleted to stop sharing them. Since the data cannot be restored faithfully, the
    # downgrade is refused unless the trash is empty (the same policy as 20260826_01); empty it first
    # by purging the memos.
    # 検査と列の削除の間に新しい削除が入らないよう、書き込みを止めてから数える。
    # Writes are blocked before counting so no memo can be trashed between the check and the drop.
    connection = op.get_bind()
    connection.execute(text("LOCK TABLE memo_entries IN SHARE ROW EXCLUSIVE MODE"))
    trashed = connection.execute(
        text("SELECT count(*) FROM memo_entries WHERE deleted_at IS NOT NULL")
    ).scalar_one()
    if trashed:
        raise RuntimeError(
            f"20261005_01 cannot be downgraded while {trashed} trashed memo(s) exist: dropping deleted_at "
            "would restore memos the user deleted. Purge the memo trash first, then retry."
        )
    # 列を落とすと部分索引 idx_memo_entries_deleted_at も一緒に消える。
    # Dropping the column also drops the partial index idx_memo_entries_deleted_at.
    op.execute("ALTER TABLE memo_entries DROP COLUMN IF EXISTS deleted_at")
