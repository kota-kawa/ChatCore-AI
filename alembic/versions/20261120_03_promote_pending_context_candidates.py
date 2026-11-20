"""Move the pending memory candidates that fit under the active-fact cap into memory.

Revision ID: 20261120_03
Revises: 20261120_02
Create Date: 2026-11-20

Pending candidates are no longer reviewed on the memory screen: extracted content is saved directly, and at the
cap an auto-saved memory the owner never touched is replaced (ADR 0023). The candidates that piled up before
passed the same extraction thresholds as directly saved content, so they become memory instead of being
dropped. Per user, the most important pending candidates (then the most confident, then the smallest id) fill
the free active slots (200 minus the active facts). Each moved fact looks like content the chat saved
automatically: source_kind 'chat', unconfirmed (last_confirmed_at NULL), the candidate's confidence, importance,
type, title, content and source_ref, an embedding waiting to be generated, and created_at carried over from the
candidate so it ranks by when it was extracted if the cap ever replaces it. A candidate carried no quote, so no
source row is created. The candidate becomes 'approved' and points at its fact (promoted_fact_id).
Pending candidates that did not fit stay as they are: this revision is expand-only (scripts/check_migration_safety.py
rejects DELETE), the new code never reads pending candidates, and the revision that drops the table removes them.

# migration-review: approved-data-backfill
Every pending candidate is read once and at most (200 - active facts) per user are inserted; context_facts is
capped per user, so the statement stays small. Candidates are updated only to link them to the new facts.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261120_03"
down_revision: str | Sequence[str] | None = "20261120_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 旧バージョンのコードは同時に動いていて、事実を足すときに利用者単位の advisory lock（第 1 キー 1129601108、第 2 キー user_id）を取る。
    # 同じロックを取ってから件数を数えるので、空きの計算と挿入の間に旧コードが事実を足して上限を超えることがない。
    # 旧コードは 1 トランザクションに 1 つしかロックを取らないため、ここで複数のロックを持っても循環待ちにならない。
    # The older code color keeps running and takes the per-user advisory lock (first key 1129601108, second key
    # user_id) when it adds facts. Taking the same lock before counting means it cannot add a fact between the free-slot
    # count and the insert and overshoot the cap. The older code holds one lock per transaction, so holding several here
    # cannot form a wait cycle.
    op.execute(
        """
        SELECT pg_advisory_xact_lock(1129601108, owner.user_id)
          FROM (
              SELECT DISTINCT user_id
                FROM context_fact_candidates
               WHERE status = 'pending'
          ) AS owner
        """
    )

    # 空きは利用者ごとに 200（アプリの上限 MAX_ACTIVE_CONTEXT_FACTS）から有効な事実の数を引いた数。位置が空き以下の候補を移す。
    # 事実の id は先に nextval で決め、同じ値で候補の promoted_fact_id を埋める。nextval は位置で絞った後の行にだけ評価される。
    # The free slots per user are 200 (the app's MAX_ACTIVE_CONTEXT_FACTS) minus the active facts; candidates whose position
    # is within it move. Fact ids are drawn with nextval first so the same value fills promoted_fact_id. nextval is
    # evaluated only for the rows that survive the position filter.
    op.execute(
        """
        WITH ranked AS (
            SELECT candidate.id,
                   candidate.user_id,
                   candidate.fact_type,
                   candidate.title,
                   candidate.content,
                   candidate.source_ref,
                   candidate.importance,
                   candidate.confidence,
                   candidate.created_at,
                   row_number() OVER (
                       PARTITION BY candidate.user_id
                       ORDER BY candidate.importance DESC, candidate.confidence DESC, candidate.id ASC
                   ) AS position
              FROM context_fact_candidates AS candidate
             WHERE candidate.status = 'pending'
        ),
        selected AS (
            SELECT ranked.id AS candidate_id,
                   ranked.user_id,
                   ranked.fact_type,
                   ranked.title,
                   ranked.content,
                   ranked.source_ref,
                   ranked.importance,
                   ranked.confidence,
                   ranked.created_at,
                   nextval(pg_get_serial_sequence('context_facts', 'id')) AS fact_id
              FROM ranked
             WHERE ranked.position <= 200 - (
                 SELECT count(*)
                   FROM context_facts AS fact
                  WHERE fact.user_id = ranked.user_id
                    AND fact.status = 'active'
             )
        ),
        inserted AS (
            INSERT INTO context_facts (
                id, user_id, fact_type, title, content, source_kind, source_ref,
                importance, confidence, status, embedding_status, created_at
            )
            SELECT selected.fact_id, selected.user_id, selected.fact_type, selected.title, selected.content,
                   'chat', selected.source_ref, selected.importance, selected.confidence,
                   'active', 'pending', selected.created_at
              FROM selected
        )
        UPDATE context_fact_candidates AS candidate
           SET status = 'approved',
               promoted_fact_id = selected.fact_id,
               revision = candidate.revision + 1
          FROM selected
         WHERE candidate.id = selected.candidate_id
        """
    )


def downgrade() -> None:
    # 移した記憶は元に戻さない。移した事実と、本人が使い始めた後の事実を区別できず、承認済みに変えた候補を承認待ちへ
    # 戻すと、旧バージョンの画面でもう一度承認できてしまい事実が重複するため。スキーマは変わらないので何もしない。
    # The moved memories are not reverted: they cannot be told apart from facts the owner has used since, and putting the
    # candidates back to pending would let the older screen approve them again and duplicate the facts. The schema is
    # unchanged, so there is nothing to undo.
    pass
