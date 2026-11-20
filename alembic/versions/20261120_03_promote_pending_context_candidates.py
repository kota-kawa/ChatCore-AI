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
Every pending candidate is read once, and per user at most (200 - active facts) rows are inserted, so no user ends
above the cap. The number of users holding pending candidates is not bounded, so the statement is one set-based
INSERT, not a per-user loop. Candidates are updated only to link them to the new facts (status 'pending' only: one
the older code rejected in the meantime is left alone). context_facts is locked in SHARE ROW EXCLUSIVE mode first:
reads continue, writes wait for the commit, and the wait is bounded by lock_timeout (the revision fails and can be
rerun rather than stalling every write behind it).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261120_03"
down_revision: str | Sequence[str] | None = "20261120_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 旧バージョンのコードは同時に動いていて、事実を足すと有効な件数が変わる。空きの計算と挿入の間に旧コードが足すと上限を超えるので、
    # context_facts を SHARE ROW EXCLUSIVE で表ロックし、読み取りは通したまま、書き込みはこのトランザクションの終了まで待たせる。
    # 利用者単位の advisory lock は、承認待ちを持つ利用者の数だけロックを持つことになり、ロック表（max_locks_per_transaction ×
    # max_connections）を使い切って失敗し得るので使わない。表ロックは 1 つで利用者数に依らない。
    # 長いトランザクションの後ろで待ち続けると全ての書き込みが止まるため、待ち時間に上限を付ける。取れなければ revision は失敗し、
    # 何も変わらないので、書き込みの少ない時間に再実行できる。上限は後続の文（行ロックの待ち）にも効く。
    # 旧コードの承認・却下が候補の行を持ったまま事実の挿入を待つ場合も、この上限か PostgreSQL のデッドロック検出で失敗して再実行になる。
    # The older code color keeps running, and adding a fact changes the active count. If it added one between the
    # free-slot count and the insert, a user would end above the cap, so context_facts is locked in SHARE ROW EXCLUSIVE
    # mode: reads continue and writes wait until this transaction ends. A per-user advisory lock is not used: it would
    # hold one lock per user with pending candidates and can exhaust the lock table (max_locks_per_transaction x
    # max_connections). One table lock does not depend on the number of users.
    # Waiting behind a long transaction would stall every write, so the wait is bounded. If the lock cannot be taken the
    # revision fails with nothing changed and can be rerun at a quieter time. The bound also covers row-lock waits in the
    # later statements; an older approve or reject that holds a candidate row while waiting to insert a fact ends in
    # this timeout or in PostgreSQL's deadlock detection, and the revision is rerun.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE context_facts IN SHARE ROW EXCLUSIVE MODE")

    # 空きは利用者ごとに 200（アプリの上限 MAX_ACTIVE_CONTEXT_FACTS）から有効な事実の数を引いた数。位置が空き以下の候補を移す。
    # 候補は先に FOR UPDATE で行ロックして取り、旧コードが同時に却下・承認した候補（行ロックの再評価で外れる）から事実を作らない。
    # 事実の id は先に nextval で決め、同じ値で候補の promoted_fact_id を埋める。nextval は位置で絞った後の行にだけ評価される。
    # The free slots per user are 200 (the app's MAX_ACTIVE_CONTEXT_FACTS) minus the active facts; candidates whose position
    # is within it move. Candidates are first read with FOR UPDATE row locks, so a candidate the older code rejects or approves
    # meanwhile (dropped by the lock's re-check) never produces a fact. Fact ids are drawn with nextval first so the same
    # value fills promoted_fact_id. nextval is evaluated only for the rows that survive the position filter.
    op.execute(
        """
        WITH pending AS (
            SELECT candidate.id,
                   candidate.user_id,
                   candidate.fact_type,
                   candidate.title,
                   candidate.content,
                   candidate.source_ref,
                   candidate.importance,
                   candidate.confidence,
                   candidate.created_at
              FROM context_fact_candidates AS candidate
             WHERE candidate.status = 'pending'
               FOR UPDATE
        ),
        ranked AS (
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
              FROM pending AS candidate
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
           AND candidate.status = 'pending'
        """
    )
    # この revision のあとに同じトランザクションで走る文へ、短い待ち時間を引き継がない。
    # Do not carry the short wait limit into statements that run after this revision in the same transaction.
    op.execute("SET LOCAL lock_timeout TO DEFAULT")


def downgrade() -> None:
    # 移した記憶は元に戻さない。移した事実と、本人が使い始めた後の事実を区別できず、承認済みに変えた候補を承認待ちへ
    # 戻すと、旧バージョンの画面でもう一度承認できてしまい事実が重複するため。スキーマは変わらないので何もしない。
    # The moved memories are not reverted: they cannot be told apart from facts the owner has used since, and putting the
    # candidates back to pending would let the older screen approve them again and duplicate the facts. The schema is
    # unchanged, so there is nothing to undo.
    pass
