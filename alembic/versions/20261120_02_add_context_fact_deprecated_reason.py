"""Record why a memory fact was deprecated.

Revision ID: 20261120_02
Revises: 20261120_01
Create Date: 2026-11-20

`deprecated_reason` tells an owner's own deprecation ('user') from the automatic replacement made when the
active-fact cap is reached ('capacity'). The CHECK also lists 'superseded' and 'merged', which no code writes
yet: later changes will use them, and widening a CHECK afterwards means dropping the constraint, which
scripts/check_migration_safety.py rejects, so every value is allowed from the start.
NULL means "not recorded": active facts, and facts deprecated before this revision (no backfill; they were the
owner's, so readers treat NULL like 'user').

# migration-review: approved-validated-check
The CHECK is added in the same statement as the new column, so every row is NULL and the validation cannot
fail or hold a long scan (context_facts is capped per user).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261120_02"
down_revision: str | Sequence[str] | None = "20261120_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 追加のみ（expand）。列は NULL 許容で既存行は触らないため、旧バージョンのコードが同時に動いても壊れない
    # （旧コードは列を書かず、復元しても NULL に戻さない。新しいコードは status が deprecated の行だけ理由を読む）。
    # Expand only: the column is nullable and no existing row is touched, so an older code color keeps working (it
    # writes no reason and does not clear it on restore; the new code reads the reason only on deprecated rows).
    op.execute(
        """
        ALTER TABLE context_facts
            ADD COLUMN deprecated_reason VARCHAR(20),
            ADD CONSTRAINT ck_context_facts_deprecated_reason
                CHECK (deprecated_reason IS NULL OR deprecated_reason IN ('user', 'superseded', 'merged', 'capacity'))
        """
    )


def downgrade() -> None:
    # 理由は失われる（旧スキーマには持ち場所がない）。事実の状態そのものは変わらない。実行前に論理バックアップを取ること。
    # The reasons are lost (the old schema has nowhere to keep them); fact statuses are unchanged.
    # Take a logical backup before running this.
    op.execute(
        """
        ALTER TABLE context_facts
            DROP CONSTRAINT IF EXISTS ck_context_facts_deprecated_reason,
            DROP COLUMN IF EXISTS deprecated_reason
        """
    )
