"""記憶(context_facts)の自動抽出の保存を永続化する。抽出した内容は未確認の事実として保存し、有効件数が上限のときは、
自動保存のまま本人が手を入れていない事実を無効化して入れ替える。照合の結果があれば、食い違う古い事実を無効化して新しい事実に
置き換える(置き換え先を記録する)か、言い換えとして出典だけを足す。重複判定には本人が却下した候補(context_fact_candidates)も読む。
自動抽出の設定(users.context_auto_extract_enabled)も扱う。services/context_vault_candidate_service.py から使われる。

Async SQLAlchemy persistence for automatically extracted memory.
Extracted content is saved as unconfirmed facts, and at the active-fact cap an auto-saved fact the owner never touched is
deprecated to make room. Given a reconciliation result, an outdated contradicting fact is deprecated and replaced by the new
one (recording the replacement), or a reworded one only gains a source. Duplicate checks also read the candidates the owner
rejected (context_fact_candidates).
Also covers the extraction setting (users.context_auto_extract_enabled); used by services/context_vault_candidate_service.py.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from services.api_errors import ResourceNotFoundError
from services.context_vault_bm25 import find_bm25_duplicates
from services.context_vault_reconcile import CandidatePlan, resolve_candidate_action
from services.datetime_serialization import serialize_datetime_iso
from services.error_messages import ERROR_CONTEXT_EXTRACTION_SETTINGS_NOT_FOUND
from services.models import ContextFact, ContextFactCandidate, User
from services.repositories.context_fact_repository import MAX_ACTIVE_CONTEXT_FACTS, matchable_fact_clause
from services.repositories.context_fact_source_repository import ContextFactSourceRepository, last_mentioned_at

logger = logging.getLogger(__name__)

# 日本語: 重複判定(BM25)に使う既存文書の最大件数。
# English: The maximum number of existing documents used for BM25 duplicate detection.
MAX_CONTEXT_DEDUPLICATION_DOCUMENTS = 500
# 日本語: advisory lock の名前空間(第 1 キー)。context_fact_repository と同じ値で、第 2 キーに user_id を渡すため、
# 同一ユーザーの抽出の保存と事実の書き込みが同じロックで直列化される。
# English: Advisory-lock namespace (first key), the same value as in context_fact_repository; with user_id as the second key,
# extraction saves and fact writes of one user are serialized by the same lock.
_CONTEXT_VAULT_LOCK_NAMESPACE = 1129601108  # ASCII "CTXT"

_FACT_COLUMNS = (
    "id",
    "user_id",
    "fact_type",
    "title",
    "content",
    "source_kind",
    "source_ref",
    "source_client_id",
    "importance",
    "status",
    "revision",
    "embedding_status",
    "confidence",
    "last_confirmed_at",
    "created_at",
    "updated_at",
)
_FACT_RETURNING = tuple(getattr(ContextFact, name) for name in _FACT_COLUMNS)


# 日本語: ORM モデル・Row・マッピングのどれが来ても、指定列だけの dict にそろえる(RETURNING の結果と ORM 行
# を同じ関数でシリアライズするため)。
# English: Normalizes an ORM model, Row or mapping into a dict of the given columns so RETURNING results and ORM rows share one serializer.
def _record(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(row, ContextFact):
        return {name: getattr(row, name) for name in columns}
    mapping = row if hasattr(row, "keys") else getattr(row, "_mapping", row)
    return {
        name: mapping[name] if name in mapping else getattr(mapping, name, None)
        for name in columns
    }


def _serialize_fact(row: Any) -> dict[str, Any]:
    record = _record(row, _FACT_COLUMNS)
    return {
        "id": int(record["id"]),
        "user_id": int(record["user_id"]),
        "fact_type": str(record["fact_type"]),
        "title": str(record["title"] or ""),
        "content": str(record["content"] or ""),
        "source_kind": str(record["source_kind"] or "chat"),
        "source_ref": str(record["source_ref"]) if record["source_ref"] is not None else None,
        "source_client_id": (
            str(record["source_client_id"])
            if record["source_client_id"] is not None
            else None
        ),
        "importance": int(record["importance"] if record["importance"] is not None else 50),
        "status": str(record["status"] or "active"),
        "revision": max(int(record["revision"] or 1), 1),
        "embedding_status": str(record["embedding_status"] or "pending"),
        "confidence": float(record["confidence"]) if record["confidence"] is not None else None,
        "last_confirmed_at": serialize_datetime_iso(record["last_confirmed_at"]),
        "created_at": serialize_datetime_iso(record["created_at"]),
        "updated_at": serialize_datetime_iso(record["updated_at"]),
    }


class ContextFactCandidateRepository:
    """所有ユーザーで絞った抽出の保存と設定の永続化。トランザクションは呼び出し側が持つ。

    Owner-scoped persistence of extraction saves and the setting; transaction ownership stays with the caller.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 日本語: トランザクション終了まで続くユーザー単位のロック。上限判定や重複判定と挿入の間に別リクエストが割り込むのを防ぐ。
    # English: Transaction-scoped per-user lock, so another request cannot slip in between the cap/duplicate checks and the insert.
    async def _lock_user(self, user_id: int) -> None:
        await self.session.execute(
            select(func.pg_advisory_xact_lock(_CONTEXT_VAULT_LOCK_NAMESPACE, user_id))
        )

    # 日本語: 候補ごとに、重複している相手の文書(同じバッチで先に残った候補を含む)を返す。重複していない候補は None。比較対象は
    # 有効な事実・本人が無効化した事実(matchable_fact_clause)と、本人が却下した候補。ロックは取らないので、保存の前に重複しない候補を
    # 絞る読み取り(照合)と、ロックの中での保存の両方から使う。
    # English: Returns, per candidate, the document it duplicates (including an earlier candidate of the same batch), or None when it
    # is unique. The corpus is active facts, facts the owner deprecated (matchable_fact_clause) and rejected candidates. It takes no
    # lock, so both the read that narrows candidates before reconciliation and the save inside the lock can use it.
    async def find_duplicate_matches(
        self,
        user_id: int,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any] | None]:
        return find_bm25_duplicates(candidates, await self._duplicate_corpus(user_id))

    # 日本語: 重複判定の比較対象(BM25 にかける既存の文書)。有効な事実を優先(priority 0)し、本人が無効化した事実は 1、却下済みの候補は
    # 最後(2)に回し、上限件数で切る。読み取りは事実と却下済みの候補の 2 回。
    # English: The corpus of existing documents the duplicate check runs BM25 against. Active facts rank first (priority 0), facts
    # the owner deprecated next (1) and rejected candidates last (2), cut at the cap. Two reads: facts and rejected candidates.
    async def _duplicate_corpus(self, user_id: int) -> list[dict[str, Any]]:
        facts_result = await self.session.execute(
            select(
                ContextFact.id,
                ContextFact.revision,
                ContextFact.fact_type,
                ContextFact.title,
                ContextFact.content,
                ContextFact.updated_at,
                ContextFact.status,
            ).where(
                ContextFact.user_id == user_id,
                # 日本語: 上限で外した事実(capacity)と新しい事実に置き換えた事実(superseded)は、本人が取り消したわけではないので
                # 比較しない。理由が NULL の無効化済みの事実はこの列の追加前の記録で、本人が無効化したものとして扱う。
                # English: A fact the cap removed (capacity) or a newer fact replaced (superseded) is not something the owner undid,
                # so it is not compared. A deprecated fact with a NULL reason predates the column and counts as the owner's.
                matchable_fact_clause(),
            )
        )
        candidates_result = await self.session.execute(
            select(
                ContextFactCandidate.fact_type,
                ContextFactCandidate.title,
                ContextFactCandidate.content,
                ContextFactCandidate.updated_at,
                ContextFactCandidate.status,
            ).where(
                ContextFactCandidate.user_id == user_id,
                ContextFactCandidate.status == "rejected",
            )
        )
        # 日本語: 上限件数で切ったときに有効な内容を残すため、優先度の順に並べる。同順位では更新が新しいものが先。
        # English: Ordered by rank so the cap drops the least relevant documents; newer updates win within a rank.
        existing_documents = [
            {
                "fact_id": int(row.id),
                "fact_revision": int(row.revision),
                "fact_status": str(row.status),
                "fact_type": str(row.fact_type),
                "title": str(row.title or ""),
                "content": str(row.content or ""),
                "updated_at": row.updated_at,
                "priority": 0 if row.status == "active" else 1,
            }
            for row in facts_result
        ] + [
            {
                "fact_type": str(row.fact_type),
                "title": str(row.title or ""),
                "content": str(row.content or ""),
                "updated_at": row.updated_at,
                "priority": 2,
            }
            for row in candidates_result
        ]
        existing_documents.sort(
            key=lambda document: (
                int(document["priority"]),
                -(
                    document["updated_at"].timestamp()
                    if document["updated_at"] is not None
                    else float("-inf")
                ),
            )
        )
        return existing_documents[:MAX_CONTEXT_DEDUPLICATION_DOCUMENTS]

    async def store_extracted(
        self,
        user_id: int,
        candidates: list[dict[str, Any]],
        *,
        room_id: str | None = None,
        user_message_id: int | None = None,
        plans: dict[int, CandidatePlan] | None = None,
    ) -> list[dict[str, Any]]:
        """重複を除いた抽出結果を、未確認の事実として保存する。有効件数が上限のときは、自動保存のまま本人が手を入れていない
        事実を 1 件ずつ無効化(理由 capacity)して入れ替える。保存した事実の一覧を返す。

        重複判定は、有効な事実・本人が無効化した事実(理由 user か未記録)・本人が却下した候補との BM25 と、却下済み候補の
        fingerprint で行う。上限で外した事実(capacity)と、置き換えた事実(superseded)、承認待ち・承認済みの候補は比較しないので、
        外れた内容が再び話題になれば新しい事実として保存できる。入れ替えられる事実が無いときは、新しい内容を保存しない。
        room_id があり候補に evidence(本人発話の引用)があるときは出典行を残す。保存した事実には同じトランザクションで
        1 件入れ、有効な事実と重複した分は、その事実へ出典を足す(事実の行は更新しない)。

        plans は、照合の結果(候補の添字から)。照合の対象は、重複しなかった候補と、BM25 の最良一致が有効な事実だった候補。
        最良一致が本人の無効化した事実・却下済みの候補・同じバッチの候補のときは何も保存しない(plans があっても変わらない)。
        有効な事実に一致した候補は、事前の照合も同じ事実に一致していて判定があるときだけ、その判定を使う(判定が無い・事前と一致が
        食い違うときは、従来どおりその事実への再言及)。重複しなかった候補で事前の照合も一致が無ければ、その判定を使う(判定が無ければ
        新しい事実)。add の判定は新しい事実として保存する。supersede は、対象が
        判定の時点の revision のままの有効な事実なら、対象を無効化(理由 superseded)して新しい事実を入れ、対象に置き換え先を記録する
        (有効件数は変わらないので入れ替えは起こさない)。対象が変わっていたら置き換えず、新しい事実として保存する。mention は
        対象へ出典だけを足し、skip は何も保存しない。plans の embedding があれば、新しい事実にそのまま保存する。

        Save unique extracted content as unconfirmed facts. At the active-fact cap, replace facts one at a time by
        deprecating an auto-saved fact the owner never touched (reason capacity). Returns the facts saved.
        Duplicates are judged by BM25 against active facts, facts the owner deprecated (reason user or unrecorded) and
        rejected candidates, plus the fingerprint of rejected candidates. Facts the cap removed (capacity), facts a newer
        fact replaced (superseded) and pending/approved candidates are not compared, so content that was pushed out can be
        saved again as a new fact. With nothing replaceable, the new content is not saved.
        With a room_id and a candidate evidence quote, a source row is kept: one in the same transaction for a saved
        fact, and one added to the matched fact when the content duplicates an active fact (the fact row is not updated).

        plans holds the reconciliation results (by candidate index). Reconciliation covers candidates that were not duplicates and
        candidates whose BM25 best match was an active fact. When the best match is a fact the owner deprecated, a rejected
        candidate or a same-batch candidate nothing is saved, plan or not. A candidate that matched an active fact uses its
        decision only when reconciliation matched the same fact and decided something (with no decision, or a different earlier
        match, it is a re-mention of that fact as before). A unique candidate whose earlier match was also none uses its decision
        (a new fact without one). An add decision saves a new fact. A supersede deprecates the target (reason superseded) when it
        is still an active fact at the revision it was judged at, inserts the new fact and records the replacement on the target; the
        active count does not change, so it never triggers a replacement at the cap. A changed target is not replaced and the
        content is saved as a new fact. A mention only adds a source to the target and a skip saves nothing. An embedding in
        the plan is stored with the new fact as is.
        """
        await self._lock_user(user_id)
        active_count = await self.session.scalar(
            select(func.count(ContextFact.id)).where(
                ContextFact.user_id == user_id,
                ContextFact.status == "active",
            )
        )
        free_fact_slots = max(MAX_ACTIVE_CONTEXT_FACTS - int(active_count or 0), 0)
        corpus = await self._duplicate_corpus(user_id)
        matches = find_bm25_duplicates(candidates, corpus)
        # 日本語: 本人が無効化した事実(priority 1)と却下済みの候補(priority 2)だけの比較対象。有効な事実に一致した候補が、
        # 新しい事実として保存される前に、本人が消した内容や却下した内容と重複していないかを確かめる(BM25 は最良一致 1 件しか
        # 返さない)。追加の読み取りはしない。
        # English: The corpus of only facts the owner deprecated (priority 1) and rejected candidates (priority 2). A candidate that
        # matched an active fact is checked against it before it can be saved as a new fact, so content the owner removed or rejected
        # is not saved again (BM25 returns only the single best match). No extra read.
        owner_removed_corpus = [document for document in corpus if int(document["priority"]) >= 1]

        saved_facts: list[dict[str, Any]] = []
        replaced_count = 0
        superseded_count = 0
        # 日本語: このバッチで保存した事実と再言及を記録した事実は、同じバッチの入れ替えの対象にしない。
        # English: Facts saved or re-mentioned in this batch are never replaced by a later candidate of the same batch.
        protected_fact_ids: set[int] = set()
        replacement_exhausted = False
        for index, (candidate, match) in enumerate(zip(candidates, matches, strict=True)):
            # 日本語: 重複した相手が有効な事実でなければ(同一バッチの候補・本人が無効化した事実・却下済みの候補)、何も保存しない。
            # English: When the match is not an active fact (a same-batch candidate, a fact the owner deprecated, or a rejected
            # candidate), nothing is saved.
            matched_fact_id: int | None = None
            matched_revision: int | None = None
            if match is not None:
                if match.get("fact_status") != "active":
                    continue
                matched_fact_id = int(match["fact_id"])
                matched_revision = int(match["fact_revision"])
            # 日本語: 事前の照合の結果は、事前の BM25 の一致とここでの一致が同じときだけ使う。判定が無い・食い違うときは従来の挙動で、
            # 有効な事実と重複した分は、その事実への再言及として出典だけを足し、重複しなかった分は新しい事実として保存する。
            # English: The earlier reconciliation result is used only when the BM25 match then and here agree. With no decision or a
            # disagreement the earlier behavior applies: a duplicate of an active fact is a repeat mention (only a source is added),
            # and a unique candidate is saved as a new fact.
            plan = (plans or {}).get(index) or CandidatePlan()
            # 日本語: 有効な事実に一致した候補は、新しい事実になる(add、置き換え、置き換えできず add に倒れる場合を含む)前に、本人が
            # 無効化した事実・却下済みの候補とも重複していないかを確かめる(BM25 は最良一致 1 件しか返さないため)。重複していれば新しい事実は
            # 作らず、照合の導入前と同じく最良一致の有効な事実への再言及になる(その事実が変わっていれば出典は足されない)。この規則は
            # resolve_candidate_action が持つ。重複しなかった候補(最良一致なし)は定義上どちらとも重複しないので確かめない。置き換え
            # (superseded)・上限(capacity)・統合(merged)で無効化した事実は比較対象に無く、この抑止は働かない。
            # English: A candidate that matched an active fact is checked, before it can become a new fact (add, a replacement, or a
            # replacement that falls back to an add), against facts the owner deprecated and rejected candidates, because BM25 returns
            # only the single best match. On a match no new fact is made and, as before reconciliation existed, it becomes a
            # re-mention of the best-matching active fact (no source is added if that fact changed). resolve_candidate_action owns
            # the rule. A unique candidate (no best match) duplicates neither by definition, so it is not checked. Facts deprecated by
            # replacement (superseded), the cap (capacity) or merging (merged) are not in the corpus, so this does not apply to them.
            duplicates_owner_removed = (
                matched_fact_id is not None and find_bm25_duplicates([candidate], owner_removed_corpus)[0] is not None
            )
            resolution = resolve_candidate_action(
                plan, matched_fact_id, matched_revision, duplicates_owner_removed=duplicates_owner_removed
            )
            # 日本語: 本人が却下した候補と同じ fingerprint の内容は、保存しない。重複しなかった候補は常に確かめ(従来どおり)、有効な事実に
            # 一致した候補は、新しい事実として保存する判定(add・supersede)のときだけ確かめる(再言及・何もしない判定には関係しない)。
            # English: Content whose fingerprint matches a candidate the owner rejected is not saved. A unique candidate is always
            # checked (as before); one that matched an active fact is checked only when it would be saved as a new fact (add or
            # supersede), since a re-mention or a decision to save nothing does not save content.
            if matched_fact_id is None or resolution.action in ("add", "supersede"):
                already_rejected = await self.session.scalar(
                    select(ContextFactCandidate.id).where(
                        ContextFactCandidate.user_id == user_id,
                        ContextFactCandidate.fingerprint == candidate["fingerprint"],
                        ContextFactCandidate.status == "rejected",
                    )
                )
                if already_rejected is not None:
                    continue
            if resolution.action == "skip":
                continue
            if resolution.action == "mention" and resolution.target_fact_id is not None:
                protected_fact_ids.add(resolution.target_fact_id)
                await self._record_source(
                    user_id,
                    resolution.target_fact_id,
                    candidate,
                    room_id,
                    user_message_id,
                    expected_revision=resolution.target_revision,
                )
                continue
            if resolution.action == "supersede":
                superseding_fact = await self._supersede_fact(user_id, candidate, plan, room_id, user_message_id)
                if superseding_fact is not None:
                    saved_facts.append(superseding_fact)
                    superseded_count += 1
                    protected_fact_ids.add(int(superseding_fact["id"]))
                    continue
                # 日本語: 対象が判定の後に変わっていたときは置き換えず、新しい事実として下で保存する(従来の挙動)。
                # English: A target that changed after it was judged is not replaced; the content is saved as a new fact below.
            if len(saved_facts) - replaced_count - superseded_count >= free_fact_slots:
                if replacement_exhausted:
                    continue
                if not await self._deprecate_replaceable_fact(user_id, protected_fact_ids):
                    replacement_exhausted = True
                    continue
                replaced_count += 1
            fact = await self._insert_unconfirmed_fact(user_id, candidate, plan.embedding)
            saved_facts.append(fact)
            protected_fact_ids.add(int(fact["id"]))
            await self._record_source(user_id, int(fact["id"]), candidate, room_id, user_message_id)
        if replaced_count:
            logger.info("Replaced memory facts at the cap.", extra={"user_id": user_id, "replaced_count": replaced_count})
        if superseded_count:
            logger.info("Superseded memory facts.", extra={"user_id": user_id, "superseded_count": superseded_count})
        return saved_facts

    # 日本語: 対象の有効な事実を、判定の時点の revision のままであることを確かめて無効化し(理由 superseded、revision を進める)、
    # 新しい事実を未確認として入れ、対象に置き換え先を記録する。更新は 1 文で条件(本人のもの・有効・revision)を確かめるので、
    # 判定の後に本人が編集・無効化した対象は 0 行になり、何も変えずに None を返す(呼び出し側は新しい事実として保存する)。
    # 対象の行はこの更新で行ロックを取る。
    # English: Deprecate the active target after checking it is still at the revision it was judged at (reason superseded, revision
    # advanced), insert the new fact as unconfirmed, and record the replacement on the target. The update checks the conditions (the
    # owner's, active, revision) in one statement, so a target the owner edited or deprecated after the judgement matches zero rows
    # and None is returned without changing anything (the caller saves the content as a new fact). The update takes the row lock.
    async def _supersede_fact(
        self,
        user_id: int,
        candidate: dict[str, Any],
        plan: CandidatePlan,
        room_id: str | None,
        user_message_id: int | None,
    ) -> dict[str, Any] | None:
        target_id = plan.resolution.target_fact_id
        deprecated = await self.session.execute(
            update(ContextFact)
            .where(
                ContextFact.id == target_id,
                ContextFact.user_id == user_id,
                ContextFact.status == "active",
                ContextFact.revision == plan.resolution.target_revision,
            )
            .values(
                status="deprecated",
                deprecated_reason="superseded",
                revision=ContextFact.revision + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(ContextFact.id)
        )
        if deprecated.scalar_one_or_none() is None:
            return None
        fact = await self._insert_unconfirmed_fact(user_id, candidate, plan.embedding)
        await self.session.execute(
            update(ContextFact)
            .where(ContextFact.id == target_id, ContextFact.user_id == user_id)
            .values(superseded_by_fact_id=fact["id"])
        )
        await self._record_source(user_id, int(fact["id"]), candidate, room_id, user_message_id)
        return fact

    # 日本語: 上限のとき、自動保存のまま本人が手を入れていない有効な事実を 1 件無効化して理由 capacity を記録し、入れたかを返す。
    # 対象は source_kind が chat で last_confirmed_at が NULL、かつ一度も更新されていない(revision が初期値の 1)事実だけ(本人の
    # 手入力・編集・承認、MCP、インポートは外れない)。復元・重要度の変更・無効化は last_confirmed_at を変えない(ADR 0016)が
    # revision を進めるので、本人が手を入れた事実はこの条件で外れる。埋め込みの保存は revision を進めない。
    # 最後に話題に出た時刻が最も古いものを選び、同じなら重要度が低いもの、それも同じなら id が小さいもの。
    # 時刻は出典(context_fact_sources.observed_at)の最大値で、出典が無い事実は created_at。observed_at は timestamptz、
    # created_at はタイムゾーン無しなので、created_at を timestamptz へ明示的に変換して比べる。created_at は CURRENT_TIMESTAMP を
    # セッションのタイムゾーンの壁時計で保存した値で、変換も同じタイムゾーンで元の時刻へ戻るため、暗黙の変換に頼らず意図を固定する。
    # 選択と無効化は 1 文で行い、対象の条件を更新側にも繰り返す。選んだ後に本人が編集した行は条件に合わなくなり、無効化されない。
    # 選ぶ側は FOR UPDATE SKIP LOCKED で、別のトランザクションが編集中（未コミット）の行を飛ばして次の候補を選ぶ。飛ばさないと、
    # 編集の確定後に更新が 0 行になり、ほかに入れ替えられる事実があっても新しい内容を捨ててしまう。
    # English: At the cap, deprecate one active fact that was auto-saved and never touched by the owner, record reason capacity, and
    # return whether one was replaced. Only facts with source_kind chat, a NULL last_confirmed_at and no update at all
    # (revision still at its initial 1) qualify (the owner's manual, edited and approved facts, MCP and imports are never
    # removed). Restoring, changing importance and deprecating leave last_confirmed_at alone (ADR 0016) but advance the
    # revision, so a fact the owner touched drops out here; storing an embedding does not advance it. The fact last
    # mentioned longest ago goes first, then the lower importance, then the smaller id. Last mention is the newest
    # context_fact_sources.observed_at, or created_at when there is no source. observed_at is timestamptz while created_at
    # is timezone-less, so created_at is cast to timestamptz explicitly: it was stored as the session-timezone wall clock of
    # CURRENT_TIMESTAMP, and the cast reads it back in the same zone, so the comparison does not rely on an implicit
    # conversion. Choosing and deprecating happen in one statement and the eligibility is repeated on the update, so a fact
    # the owner edits in between is no longer eligible and is left alone. The choosing side uses FOR UPDATE SKIP LOCKED, so
    # a row another transaction is editing (uncommitted) is skipped and the next candidate is chosen; otherwise the update
    # would hit zero rows once the edit commits and the new content would be dropped even though other facts could be
    # replaced.
    async def _deprecate_replaceable_fact(self, user_id: int, protected_fact_ids: set[int]) -> bool:
        replaceable = aliased(ContextFact)

        def eligible(model: Any) -> list[Any]:
            conditions = [
                model.user_id == user_id,
                model.status == "active",
                model.source_kind == "chat",
                model.last_confirmed_at.is_(None),
                model.revision == 1,
            ]
            if protected_fact_ids:
                conditions.append(model.id.not_in(sorted(protected_fact_ids)))
            return conditions

        last_mentioned = last_mentioned_at(replaceable)
        victim = (
            select(replaceable.id)
            .where(*eligible(replaceable))
            .order_by(last_mentioned.asc(), replaceable.importance.asc(), replaceable.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True, of=replaceable)
            .scalar_subquery()
        )
        statement = (
            update(ContextFact)
            .where(ContextFact.id == victim, *eligible(ContextFact))
            .values(
                status="deprecated",
                deprecated_reason="capacity",
                revision=ContextFact.revision + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(ContextFact.id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None

    # 日本語: 候補の evidence を出典として事実へ残す。部屋か evidence が無いとき(旧形式の呼び出し)は何もしない。
    # expected_revision は既存の事実へ足すときの、重複を判定した時点の revision（新しく作った事実では None）。
    # English: Keep the candidate's evidence as a source of the fact. Does nothing without a room or evidence (older callers).
    # expected_revision is the revision read when the duplicate was judged, for an existing fact (None for a fact just created).
    async def _record_source(
        self,
        user_id: int,
        fact_id: int,
        candidate: dict[str, Any],
        room_id: str | None,
        user_message_id: int | None,
        expected_revision: int | None = None,
    ) -> None:
        evidence = str(candidate.get("evidence") or "")
        if not room_id or not evidence:
            return
        await ContextFactSourceRepository(self.session).record_mention(
            fact_id=fact_id,
            user_id=user_id,
            chat_room_id=room_id,
            user_message_id=user_message_id,
            evidence=evidence,
            expected_revision=expected_revision,
        )

    # 日本語: 抽出した内容を事実として挿入する。last_confirmed_at は書かず NULL(本人未確認)のまま、確信度は抽出時の値を残す。
    # 本人が Web UI で編集すれば確認済みになる(ADR 0016)。embedding があれば一緒に保存する。
    # English: Insert extracted content as a fact. last_confirmed_at stays NULL (unconfirmed by the owner) and the extraction
    # confidence is kept; an owner edit in the web UI later confirms it (ADR 0016).
    async def _insert_unconfirmed_fact(
        self,
        user_id: int,
        candidate: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> dict[str, Any]:
        statement = pg_insert(ContextFact).values(
            user_id=user_id,
            fact_type=candidate["fact_type"],
            title=candidate["title"],
            content=candidate["content"],
            source_kind=candidate.get("source_kind", "chat"),
            source_ref=candidate.get("source_ref"),
            importance=candidate.get("importance", 50),
            confidence=candidate.get("confidence", 0),
            # 日本語: 照合で作った埋め込みがあれば、同じ文面の埋め込みを作り直さず、そのまま保存して ready にする。
            # English: An embedding made while reconciling is stored as is and marked ready, so the same text is not embedded again.
            **({"embedding_vector": [float(value) for value in embedding], "embedding_status": "ready"} if embedding else {}),
        ).returning(*_FACT_RETURNING)
        row = (await self.session.execute(statement)).mappings().first()
        if row is None:  # pragma: no cover - PostgreSQL RETURNING invariant
            raise RuntimeError("Extracted context fact was not returned.")
        return _serialize_fact(row)

    # 日本語: 列は NOT NULL なので None はユーザー行が読めなかったときだけ。その場合は無効として扱い、
    # 読めない相手に抽出が走らないようにする。
    # 初期オンは列の server_default(と migration)だけで表す。
    # English: The column is NOT NULL, so None only means the user row could not be read. That counts as disabled, so no
    # extraction runs for a user we cannot read. The on-by-default behavior lives only in the column's server_default (and the migration).
    async def get_extraction_settings(self, user_id: int) -> bool:
        enabled = await self.session.scalar(
            select(User.context_auto_extract_enabled).where(User.id == user_id)
        )
        return bool(enabled) if enabled is not None else False

    async def update_extraction_settings(self, user_id: int, enabled: bool) -> bool:
        statement = (
            update(User)
            .where(User.id == user_id)
            .values(context_auto_extract_enabled=bool(enabled))
            .returning(User.context_auto_extract_enabled)
        )
        result = await self.session.execute(statement)
        value = result.scalar_one_or_none()
        if value is None:
            raise ResourceNotFoundError(ERROR_CONTEXT_EXTRACTION_SETTINGS_NOT_FOUND)
        return bool(value)
