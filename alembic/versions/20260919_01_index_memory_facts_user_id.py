"""Index memory_facts.user_id so deleting an account does not scan the table.

Revision ID: 20260919_01
Revises: 20260913_02
Create Date: 2026-09-19

# migration-review: approved-blocking-index
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260919_01"
down_revision: Union[str, Sequence[str], None] = "20260913_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Expand only: this revision adds one index and changes no row, so a previous
    # Blue/Green color keeps reading and writing memory_facts unchanged.
    # 追加のみ: 索引を1本足すだけで行は触らないため、旧バージョンが動いていても挙動は変わりません。
    #
    # UserRepository.delete_account issues a DELETE against memory_facts filtered by user_id,
    # and the users -> memory_facts foreign key cascades the same way.  The only user_id index is
    # idx_memory_facts_user_updated_at, which is partial on is_active = TRUE; neither the delete
    # nor the cascade constrains is_active, so PostgreSQL could only answer them with a
    # sequential scan of memory_facts.
    # delete_account の DELETE と users からの ON DELETE CASCADE は is_active を条件にしないため、
    # 既存の部分索引（is_active = TRUE）は使えず memory_facts の全表走査になっていました。
    #
    # CREATE INDEX を CONCURRENTLY にしない理由は 20260913_02 と同じです。CONCURRENTLY は
    # op.get_context().autocommit_block() を必要として revision 単位のトランザクションを失い、
    # 失敗時に INVALID な索引が残ります。その後始末は索引の削除ですが、
    # scripts/check_migration_safety.py は upgrade 内の索引削除を拒否します。
    # Not CONCURRENTLY, for the reason 20260913_02 records: it gives up the per-revision
    # transaction and leaves an INVALID index behind on failure.
    #
    # CASCADE never matches NULL and the delete always binds a user id, so the index is partial
    # and stays smaller than the table.
    op.create_index(
        "idx_memory_facts_user_id",
        "memory_facts",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("user_id IS NOT NULL"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_memory_facts_user_id", table_name="memory_facts", if_exists=True)
