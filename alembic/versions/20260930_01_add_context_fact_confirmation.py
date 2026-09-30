"""Record how sure and how recently a personal context fact was confirmed.

Revision ID: 20260930_01
Revises: 20260928_01
Create Date: 2026-09-30

`confidence` is the extraction confidence carried over from the review candidate; facts the
owner wrote themselves keep NULL. `last_confirmed_at` is the last time the owner confirmed the
fact; NULL means unconfirmed (saved by an MCP client or imported). `updated_at` cannot serve
this purpose because a trigger advances it on every UPDATE, including embedding storage.

# migration-review: approved-data-backfill
# migration-review: approved-validated-check
The CHECK is added in the same statement as the new column, so every row is NULL and the
validation cannot fail or hold a long scan (context_facts is capped per user).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260930_01"
down_revision: Union[str, Sequence[str], None] = "20260928_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 追加のみ（expand）。両列とも NULL 許容で、旧色のコードが INSERT/UPDATE しても壊れない。
    # 型は candidates.confidence（DOUBLE PRECISION）に揃え、承認時の値を桁落ちなく引き継ぐ。
    # Expand only: both columns are nullable, so the old color keeps working. The type matches
    # context_fact_candidates.confidence so the approved value is carried over without float4 noise.
    op.execute(
        """
        ALTER TABLE context_facts
            ADD COLUMN confidence DOUBLE PRECISION,
            ADD COLUMN last_confirmed_at TIMESTAMP,
            ADD CONSTRAINT ck_context_facts_confidence
                CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
        """
    )

    # backfill は updated_at を動かさない（トリガーが無条件に進めるため一時的に止める）。
    # 並び順とカーソルが updated_at に依存しているので、既存行の値を変えてはいけない。
    # The backfill must not move updated_at: the trigger advances it unconditionally, and list
    # ordering and paging cursors depend on it. The migration runs in one transaction, so the
    # trigger cannot stay disabled after a failure.
    op.execute("ALTER TABLE context_facts DISABLE TRIGGER trg_context_facts_updated_at")

    # 抽出由来: 承認済み候補の確信度と承認時刻。候補が残っていなければ、承認と同時に作られる
    # 事実の created_at が承認時刻に等しい。
    # Extracted facts: the approved candidate's confidence and approval time. If no candidate
    # remains, the fact's created_at equals the approval time because approval inserts the fact.
    op.execute(
        """
        UPDATE context_facts AS fact
           SET confidence = candidate.confidence,
               last_confirmed_at = candidate.updated_at
          FROM context_fact_candidates AS candidate
         WHERE candidate.promoted_fact_id = fact.id
           AND candidate.status = 'approved'
           AND fact.source_kind = 'chat'
        """
    )
    op.execute(
        """
        UPDATE context_facts
           SET last_confirmed_at = created_at
         WHERE source_kind = 'chat'
           AND last_confirmed_at IS NULL
        """
    )
    # 手入力: 本人が書いた時点を最終確認とする。mcp / import は未確認のまま NULL。
    # Manual facts: the owner wrote them, so creation is the last confirmation. mcp and import
    # stay NULL (unconfirmed).
    op.execute(
        """
        UPDATE context_facts
           SET last_confirmed_at = created_at
         WHERE source_kind = 'manual'
        """
    )

    op.execute("ALTER TABLE context_facts ENABLE TRIGGER trg_context_facts_updated_at")


def downgrade() -> None:
    # 確認履歴は失われる（旧スキーマには持ち場所がない）。実行前に論理バックアップを取ること。
    # The confirmation history is lost (the old schema has nowhere to keep it); take a logical
    # backup before running this.
    op.execute(
        """
        ALTER TABLE context_facts
            DROP CONSTRAINT IF EXISTS ck_context_facts_confidence,
            DROP COLUMN IF EXISTS last_confirmed_at,
            DROP COLUMN IF EXISTS confidence
        """
    )
