"""Point a memory fact replaced by a newer one at its replacement.

Revision ID: 20261120_04
Revises: 20261120_03
Create Date: 2026-11-20

When a newly extracted memory contradicts an active one (the user moved, changed jobs, dropped a policy), the old
fact is deprecated with deprecated_reason 'superseded' and `superseded_by_fact_id` names the fact that replaced it
(ADR 0025). The reason value is already allowed by the CHECK from 20261120_02, so this revision adds only the
reference. NULL means "not replaced"; there is no backfill because nothing was replaced before this revision.
Deleting the replacement clears the reference (ON DELETE SET NULL) instead of blocking the delete or removing the
old fact.

# migration-review: approved-blocking-index
The partial index covers only rows whose reference is set, so it is empty when it is built and stays small.
CREATE INDEX CONCURRENTLY needs its own transaction and leaves an INVALID index on failure, whose cleanup is a
DROP INDEX that scripts/check_migration_safety.py rejects (the same reason as 20260919_01). The wait for the
table lock is bounded by lock_timeout below instead, and context_facts is capped per user.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261120_04"
down_revision: str | Sequence[str] | None = "20261120_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 追加のみ（expand）。列は NULL 許容で既存行は触らないため、旧バージョンのコードが同時に動いても壊れない
    # （旧コードは列を書かず、復元しても NULL に戻さない。新しいコードはこの列を status が deprecated の行でだけ意味づける）。
    # Expand only: the column is nullable and no existing row is touched, so an older code color keeps working (it
    # never writes the column and does not clear it on restore; the new code gives it meaning on deprecated rows only).
    # ALTER TABLE と CREATE INDEX は表のロックを取る。長いトランザクションの後ろで待つと、その間は context_facts の
    # 読み書きも後ろに並ぶので、待ち時間に上限を付け、取れなければ失敗させて再実行できるようにする。
    # 同じトランザクションで流れる後続の revision に上限を持ち越さないよう、最後に戻す。
    # ALTER TABLE and CREATE INDEX take table locks. Waiting behind a long transaction would queue every read and
    # write on context_facts behind it, so the wait is bounded: the revision fails and can be re-run. The limit is
    # reset at the end so it does not carry into later revisions run in the same transaction.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        ALTER TABLE context_facts
            ADD COLUMN superseded_by_fact_id INTEGER,
            ADD CONSTRAINT fk_context_facts_superseded_by
                FOREIGN KEY (superseded_by_fact_id) REFERENCES context_facts (id) ON DELETE SET NULL
        """
    )
    # 置き換え先の事実を消したとき（ON DELETE SET NULL）に、参照している行を全表走査せずに探すための子側の索引。
    # The child-side index that lets deleting a replacement find the rows pointing at it without a table scan.
    op.create_index(
        "idx_context_facts_superseded_by",
        "context_facts",
        ["superseded_by_fact_id"],
        postgresql_where=sa.text("superseded_by_fact_id IS NOT NULL"),
        if_not_exists=True,
    )
    op.execute("SET LOCAL lock_timeout TO DEFAULT")


def downgrade() -> None:
    # 置き換えの関係は失われる（旧スキーマには持ち場所がない）。事実の状態と理由そのものは変わらない。実行前に論理バックアップを取ること。
    # The replacement links are lost (the old schema has nowhere to keep them); fact statuses and reasons are unchanged.
    # Take a logical backup before running this.
    op.drop_index("idx_context_facts_superseded_by", table_name="context_facts", if_exists=True)
    op.execute(
        """
        ALTER TABLE context_facts
            DROP CONSTRAINT IF EXISTS fk_context_facts_superseded_by,
            DROP COLUMN IF EXISTS superseded_by_fact_id
        """
    )
