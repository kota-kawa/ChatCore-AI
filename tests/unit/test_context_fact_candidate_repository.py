"""ContextFactCandidateRepository（自動抽出の保存と、上限での入れ替え、抽出の設定）が発行する SQL と実行順を検証するテスト。

Tests the SQL and execution order of ContextFactCandidateRepository (storing extractions, replacement at the cap,
and the extraction setting).
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.exc import IntegrityError

from services.context_vault_reconcile import CandidatePlan, ReconcileResolution
from services.repositories.context_fact_candidate_repository import (
    ContextFactCandidateRepository,
)
from services.repositories.context_fact_repository import MAX_ACTIVE_CONTEXT_FACTS


# 日本語: 事実テーブルの 1 行分の辞書を作ります。overrides で項目を差し替えます。
# English: Build one fact-table row dict; overrides replace individual fields.
def _fact(**overrides):
    row = {
        "id": 31,
        "user_id": 7,
        "fact_type": "project",
        "title": "Edited title",
        "content": "Edited content",
        "source_kind": "chat",
        "source_ref": "room-123",
        "source_client_id": None,
        "importance": 95,
        "status": "active",
        "revision": 1,
        "confidence": 0.9,
        "last_confirmed_at": None,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


# 日本語: DB の実行結果を模したモックを作ります。mapping は 1 行取得、scalar_rows は複数行取得の戻り値になります。
# English: Build a mock of a DB execution result; mapping backs single-row reads and scalar_rows backs multi-row
# reads.
def _result(*, mapping=None, scalar_rows=None, inserted_id=None):
    result = MagicMock()
    result.mappings.return_value.first.return_value = mapping
    result.scalars.return_value.all.return_value = scalar_rows or []
    result.scalar_one_or_none.return_value = inserted_id
    return result


# 日本語: 抽出結果 1 件(サービスが検証・正規化した後の形)を作ります。
# English: Build one extraction result in the shape the service hands to the repository.
def _extracted(**overrides):
    row = {
        "fact_type": "project",
        "title": "Rust",
        "content": "Writes a compiler in Rust",
        "source_kind": "chat",
        "source_ref": "chat:room-1:message:9",
        "evidence": "I write a compiler in Rust",
        "importance": 85,
        "confidence": 0.93,
        "fingerprint": "b" * 64,
    }
    row.update(overrides)
    return row


# 日本語: store_extracted が実行する SQL の順(ロック→既存の事実→却下済みの候補→候補ごとの処理)に合わせたセッションのモックを作ります。
# inserts は候補ごとの処理で実行される文の結果を、実行順に並べたものです(入れ替えの UPDATE、事実の INSERT、出典の INSERT など)。
# English: Build a session mock that follows the order of SQL store_extracted runs (lock, existing facts, rejected
# candidates, then the per-candidate statements). inserts lists the results of those per-candidate statements in
# execution order (the replacement UPDATE, the fact INSERT, the source INSERT and so on).
def _store_session(*, active, facts=(), candidates=(), fingerprint_hit=None, fact_lock=None, inserts):
    # 日本語: session.scalar は文の内容で振り分ける（件数 → 重複した事実のロック → fingerprint の照会）。
    # English: session.scalar is answered by statement content (the count, the lock on a duplicated fact, the fingerprint lookup).
    async def scalar(statement):
        sql = str(statement.compile(dialect=dialect()))
        if "count(context_facts.id)" in sql:
            return active
        if "FOR SHARE" in sql:
            return fact_lock
        return fingerprint_hit

    session = MagicMock()
    session.scalar = AsyncMock(side_effect=scalar)
    session.begin_nested = MagicMock(side_effect=lambda: _Savepoint())
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(),
            iter(list(facts)),
            iter(list(candidates)),
            *inserts,
        ]
    )
    return session


# 日本語: session.begin_nested() の代わりに使う SAVEPOINT。中の例外は握りつぶさず、巻き戻したかを記録します。
# English: Stand-in for session.begin_nested(): exceptions inside propagate, and it records whether it rolled back.
class _Savepoint:
    rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        self.rolled_back = exc_type is not None
        return False


# 日本語: 事実テーブルの 1 行(重複判定の比較対象)を模した行を作ります。
# English: Build a row standing in for one fact-table row of the duplicate-check corpus.
def _existing_fact(status="active", fact_id=12):
    return SimpleNamespace(
        id=fact_id,
        revision=3,
        fact_type="project",
        title="Rust",
        content="Writes a compiler in Rust",
        updated_at=None,
        status=status,
    )


# 日本語: 入れ替えの UPDATE が 1 件を無効化した結果と、何も無効化しなかった結果。
# English: Results of the replacement UPDATE: one fact deprecated, and nothing replaceable.
def _replaced(fact_id=5):
    return _result(inserted_id=fact_id)


def _nothing_replaceable():
    return _result(inserted_id=None)


# 日本語: セッションが実行した文を、実行順にコンパイルして返します。
# English: Compile the statements the session executed, in execution order.
def _executed(session):
    return [call.args[0].compile(dialect=dialect()) for call in session.execute.await_args_list]


def _executed_sql(session):
    return [str(compiled) for compiled in _executed(session)]


# 日本語: AsyncSession をモックし、リポジトリが実行する SQL の内容を確認します。
# English: Mock the AsyncSession and inspect the SQL the repository executes.
class ContextFactCandidateRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_store_extracted_saves_unconfirmed_fact_when_active_slot_is_free(self):
        session = _store_session(active=3, inserts=[_result(mapping=_fact(id=41, confidence=0.93))])

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual([fact["id"] for fact in saved], [41])
        self.assertEqual(saved[0]["last_confirmed_at"], None)
        lock_sql = _executed_sql(session)[0]
        self.assertIn("pg_advisory_xact_lock", lock_sql)
        insert = _executed(session)[-1]
        self.assertIn("INSERT INTO context_facts", str(insert))
        # 本人が確かめていないので last_confirmed_at を書かず(NULL)、確信度と出典は抽出時の値を残す。
        # last_confirmed_at is not written (stays NULL); confidence and the source are kept from extraction.
        self.assertNotIn("last_confirmed_at", insert.params)
        self.assertEqual(insert.params["confidence"], 0.93)
        self.assertEqual(insert.params["source_kind"], "chat")
        self.assertEqual(insert.params["source_ref"], "chat:room-1:message:9")
        # 空きがあるので何も無効化しない。
        # Room is left, so nothing is deprecated.
        self.assertFalse(any(sql.startswith("UPDATE") for sql in _executed_sql(session)))

    async def test_store_extracted_at_the_cap_replaces_one_fact_and_saves_the_new_one_in_that_order(self):
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS,
            inserts=[_replaced(5), _result(mapping=_fact(id=41))],
        )

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual([fact["id"] for fact in saved], [41])
        statements = _executed(session)
        self.assertTrue(str(statements[3]).startswith("UPDATE context_facts SET"))
        self.assertIn("INSERT INTO context_facts", str(statements[4]))
        # 無効化の理由は capacity で、revision を進め、状態は deprecated。事実の行を消さない。
        # The reason is capacity, the revision advances, and the status is deprecated; no row is deleted.
        self.assertEqual(statements[3].params["status"], "deprecated")
        self.assertEqual(statements[3].params["deprecated_reason"], "capacity")
        self.assertIn("revision=(context_facts.revision + ", str(statements[3]).replace(" = ", "="))
        self.assertFalse(any(sql.startswith("DELETE FROM context_facts") for sql in _executed_sql(session)))

    async def test_store_extracted_only_replaces_auto_saved_facts_the_owner_never_touched(self):
        # 対象は source_kind が chat で last_confirmed_at が NULL、revision が初期値 1(一度も更新されていない)の有効な事実だけ。
        # 復元や重要度の変更は last_confirmed_at を変えないが revision を進めるので、本人が手を入れた事実は外れる。
        # 選ぶ側と更新する側の両方で条件を課す。
        # Only active facts with source_kind chat, a NULL last_confirmed_at and the initial revision 1 (never updated) qualify.
        # Restoring or changing importance leaves last_confirmed_at alone but advances the revision, so a fact the owner touched
        # drops out. Enforced both when choosing and when updating.
        session = _store_session(active=MAX_ACTIVE_CONTEXT_FACTS, inserts=[_replaced(), _result(mapping=_fact(id=41))])

        await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        update = _executed(session)[3]
        sql = " ".join(str(update).split())
        self.assertEqual(sql.count("context_facts_1.source_kind ="), 1)
        self.assertEqual(sql.count("context_facts_1.last_confirmed_at IS NULL"), 1)
        self.assertEqual(sql.count("context_facts_1.revision ="), 1)
        self.assertEqual(sql.count("context_facts_1.status ="), 1)
        self.assertEqual(sql.count("context_facts.source_kind ="), 1)
        self.assertEqual(sql.count("context_facts.last_confirmed_at IS NULL"), 1)
        self.assertEqual(sql.count("context_facts.revision ="), 1)
        self.assertEqual(sql.count("context_facts.user_id ="), 1)
        params = update.params
        self.assertEqual({params["source_kind_1"], params["source_kind_2"]}, {"chat"})
        self.assertEqual({params["status_1"], params["status_2"]}, {"active"})
        self.assertEqual({params["revision_2"], params["revision_3"]}, {1})
        self.assertEqual({params["user_id_1"], params["user_id_2"]}, {7})

    async def test_store_extracted_picks_the_longest_unmentioned_then_least_important_then_smallest_id(self):
        session = _store_session(active=MAX_ACTIVE_CONTEXT_FACTS, inserts=[_replaced(), _result(mapping=_fact(id=41))])

        await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        sql = " ".join(str(_executed(session)[3]).split())
        # 最後に話題に出た時刻 = 出典の observed_at の最大値、出典が無ければ created_at。タイムゾーン付きの observed_at と
        # 無しの created_at を暗黙の変換に任せず、created_at を timestamptz へ明示的に変換して比べる。
        # Last mention = newest source observed_at, or created_at without a source. The timestamptz observed_at is compared
        # with the timezone-less created_at through an explicit cast of created_at, not an implicit conversion.
        self.assertIn(
            "ORDER BY coalesce((SELECT max(context_fact_sources.observed_at) AS max_1 "
            "FROM context_fact_sources WHERE context_fact_sources.fact_id = context_facts_1.id), "
            "CAST(context_facts_1.created_at AS TIMESTAMP WITH TIME ZONE)) ASC, "
            "context_facts_1.importance ASC, context_facts_1.id ASC LIMIT",
            sql,
        )

    async def test_store_extracted_skips_rows_another_transaction_is_editing_when_choosing_the_replaced_fact(self):
        # 本人が編集中（未コミット）の行を選ぶと、編集の確定後に更新が 0 行になり新しい内容を捨ててしまう。選ぶ副問い合わせだけが
        # 行ロック（FOR UPDATE SKIP LOCKED）で、ロック中の行を飛ばして次の候補を選ぶ。外側の UPDATE には付けない。
        # Choosing a row the owner is editing (uncommitted) would update zero rows once the edit commits and drop the new
        # content. Only the choosing subquery takes row locks (FOR UPDATE SKIP LOCKED) so a locked row is skipped and the
        # next candidate is chosen; the outer UPDATE does not.
        session = _store_session(active=MAX_ACTIVE_CONTEXT_FACTS, inserts=[_replaced(), _result(mapping=_fact(id=41))])

        await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        sql = " ".join(str(_executed(session)[3]).split())
        self.assertEqual(sql.count("FOR UPDATE"), 1)
        self.assertIn("LIMIT %(param_1)s FOR UPDATE OF context_facts_1 SKIP LOCKED)", sql)

    async def test_store_extracted_does_not_replace_what_the_same_batch_saved_or_re_mentioned(self):
        # 1 件目は上限の入れ替えで保存(41)、2 件目は有効な事実(12)への再言及、3 件目は入れ替え。3 件目の入れ替えは
        # 保存したばかりの 41 と再言及した 12 を対象から外す。
        # The first candidate is saved by replacement (41), the second re-mentions active fact 12, and the third replaces
        # another fact without ever picking 41 (just saved) or 12 (just re-mentioned).
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS,
            facts=[_existing_fact("active", 12)],
            inserts=[
                _replaced(5),
                _result(mapping=_fact(id=41)),
                _replaced(6),
                _result(mapping=_fact(id=42)),
            ],
        )

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7,
            [
                _extracted(title="Go", content="Writes services in Go", fingerprint="c" * 64),
                _extracted(),
                _extracted(title="Kotlin", content="Builds Android apps in Kotlin", fingerprint="d" * 64),
            ],
        )

        self.assertEqual([fact["id"] for fact in saved], [41, 42])
        updates = [compiled for compiled in _executed(session) if str(compiled).startswith("UPDATE context_facts")]
        self.assertEqual(len(updates), 2)
        self.assertNotIn("NOT IN", str(updates[0]))
        self.assertEqual(updates[1].params["id_1"], [12, 41])
        self.assertEqual(updates[1].params["id_2"], [12, 41])

    async def test_store_extracted_fills_free_slots_before_replacing(self):
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS - 1,
            inserts=[_result(mapping=_fact(id=41)), _replaced(5), _result(mapping=_fact(id=42))],
        )

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7,
            [_extracted(), _extracted(title="Go", content="Writes services in Go", fingerprint="c" * 64)],
        )

        self.assertEqual([fact["id"] for fact in saved], [41, 42])
        sql = _executed_sql(session)
        self.assertTrue(sql[3].startswith("INSERT INTO context_facts"))
        self.assertTrue(sql[4].startswith("UPDATE context_facts"))
        self.assertTrue(sql[5].startswith("INSERT INTO context_facts"))

    async def test_store_extracted_saves_nothing_when_no_fact_can_be_replaced(self):
        # 入れ替えられる事実が無ければ保存しない。承認待ちにも入れず、残りの候補でも入れ替えを繰り返さない。
        # With nothing replaceable nothing is saved, nothing is queued, and later candidates do not retry the replacement.
        session = _store_session(active=MAX_ACTIVE_CONTEXT_FACTS, inserts=[_nothing_replaceable()])

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7,
            [_extracted(), _extracted(title="Go", content="Writes services in Go", fingerprint="c" * 64)],
        )

        self.assertEqual(saved, [])
        statements = _executed_sql(session)
        self.assertEqual(len(statements), 4)
        self.assertFalse(any("INSERT" in sql for sql in statements))
        self.assertFalse(any("context_fact_candidates" in sql for sql in statements[3:]))

    async def test_store_extracted_compares_active_user_deprecated_and_unrecorded_facts_but_not_capacity(self):
        session = _store_session(active=3, facts=[], inserts=[_result(mapping=_fact(id=41))])

        await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        facts_query = _executed(session)[1]
        sql = " ".join(str(facts_query).split())
        self.assertIn(
            "WHERE context_facts.user_id = %(user_id_1)s AND (context_facts.status = %(status_1)s OR "
            "context_facts.deprecated_reason IS NULL OR context_facts.deprecated_reason = %(deprecated_reason_1)s)",
            sql,
        )
        self.assertEqual(facts_query.params["status_1"], "active")
        self.assertEqual(facts_query.params["deprecated_reason_1"], "user")

    async def test_store_extracted_compares_only_rejected_candidates(self):
        session = _store_session(active=3, inserts=[_result(mapping=_fact(id=41))])

        await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        candidates_query = _executed(session)[2]
        self.assertIn("FROM context_fact_candidates", str(candidates_query))
        self.assertEqual(candidates_query.params["status_1"], "rejected")
        self.assertNotIn("pending", candidates_query.params.values())
        self.assertNotIn("approved", candidates_query.params.values())

    async def test_store_extracted_skips_content_with_a_rejected_candidate_fingerprint_only(self):
        session = _store_session(active=3, fingerprint_hit=99, inserts=[])

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual(saved, [])
        self.assertEqual(session.execute.await_count, 3)
        lookup = session.scalar.await_args_list[-1].args[0].compile(dialect=dialect())
        self.assertIn("context_fact_candidates.fingerprint =", str(lookup))
        self.assertIn("rejected", lookup.params.values())
        self.assertNotIn("pending", lookup.params.values())
        self.assertNotIn("approved", lookup.params.values())

    async def test_store_extracted_does_not_save_content_the_owner_already_deprecated(self):
        # 本人が取り消した(deprecated・理由 user か未記録)事実は重複判定の比較対象に残るので、同じ内容は再び保存されず、
        # 上限でも入れ替えを起こさない。
        # A fact the owner undid stays in the duplicate-check corpus, so the same content is not saved again and, even at the
        # cap, triggers no replacement.
        session = _store_session(active=MAX_ACTIVE_CONTEXT_FACTS, facts=[_existing_fact("deprecated")], inserts=[])

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual(saved, [])
        self.assertEqual(session.execute.await_count, 3)

    @staticmethod
    def _rejected_candidate():
        return SimpleNamespace(
            fact_type="project",
            title="Rust",
            content="Writes a compiler in Rust",
            updated_at=None,
            status="rejected",
        )

    async def test_store_extracted_does_not_save_content_matching_a_rejected_candidate(self):
        session = _store_session(active=3, candidates=[self._rejected_candidate()], inserts=[])

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual(saved, [])
        self.assertEqual(session.execute.await_count, 3)

    async def test_store_extracted_records_a_source_with_the_saved_fact(self):
        session = _store_session(
            active=3,
            inserts=[_result(mapping=_fact(id=41)), _result(inserted_id=70), MagicMock()],
        )

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="room-1", user_message_id=8
        )

        self.assertEqual([fact["id"] for fact in saved], [41])
        statements = _executed_sql(session)
        self.assertIn("INSERT INTO context_facts", statements[3])
        self.assertIn("INSERT INTO context_fact_sources", statements[4])
        self.assertIn("DELETE FROM context_fact_sources", statements[5])
        source_params = _executed(session)[4].params
        self.assertEqual(
            {41, 7, "room-1", 8, "I write a compiler in Rust"},
            set(source_params.values()),
        )
        # 同じトランザクションで作った事実なので、ロックも revision の確認もしない。
        # The fact was created in this transaction, so no lock or revision check is needed.
        self.assertFalse(any("FOR SHARE" in str(call.args[0].compile(dialect=dialect())) for call in session.scalar.await_args_list))

    async def test_store_extracted_records_a_source_with_a_fact_saved_by_replacement(self):
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS,
            inserts=[_replaced(), _result(mapping=_fact(id=41)), _result(inserted_id=70), MagicMock()],
        )

        await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()], room_id="room-1", user_message_id=8)

        statements = _executed_sql(session)
        self.assertTrue(statements[3].startswith("UPDATE context_facts"))
        self.assertTrue(statements[4].startswith("INSERT INTO context_facts"))
        self.assertTrue(statements[5].startswith("INSERT INTO context_fact_sources"))

    async def test_store_extracted_keeps_no_source_without_a_room_or_evidence(self):
        for room_id, evidence in ((None, "quote"), ("room-1", "")):
            with self.subTest(room_id=room_id, evidence=evidence):
                session = _store_session(active=3, inserts=[_result(mapping=_fact(id=41))])

                await ContextFactCandidateRepository(session).store_extracted(
                    7, [_extracted(evidence=evidence)], room_id=room_id, user_message_id=8
                )

                self.assertFalse(any("context_fact_sources" in sql for sql in _executed_sql(session)))

    async def test_store_extracted_adds_a_source_to_an_active_fact_without_updating_it(self):
        # 上限でも、有効な事実との重複は再言及として出典だけを足し、入れ替えは起こさない。
        # Even at the cap, a duplicate of an active fact only adds a source and causes no replacement.
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS,
            facts=[_existing_fact("active")],
            fact_lock=12,
            inserts=[_result(inserted_id=70), MagicMock()],
        )

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="room-1", user_message_id=8
        )

        self.assertEqual(saved, [])
        # 事実の行を FOR SHARE でロックし、重複を判定した時点の revision(3)・有効・本人の条件で確かめてから入れる。
        # The fact row is locked FOR SHARE under the revision read at duplicate time (3), active and owned, before the insert.
        lock = session.scalar.await_args_list[-1].args[0].compile(dialect=dialect())
        self.assertIn("FOR SHARE", str(lock))
        self.assertEqual({12, 7, 3, "active"}, set(lock.params.values()))
        statements = _executed_sql(session)
        self.assertIn("INSERT INTO context_fact_sources", statements[3])
        self.assertIn("DELETE FROM context_fact_sources", statements[4])
        # 事実の行は更新しない(updated_at・revision を進めない)。
        # The fact row is not updated, so updated_at and revision stay put.
        self.assertFalse(any(sql.startswith(("UPDATE context_facts", "INSERT INTO context_facts")) for sql in statements))
        source_params = _executed(session)[3].params
        self.assertIn(12, source_params.values())

    async def test_store_extracted_adds_no_source_when_the_fact_changed_after_the_duplicate_was_judged(self):
        # 更新や無効化は revision を進める。ロックの再評価で revision が合わなければ DB は行を返さず、出典は入らない。
        # An update or deprecation bumps the revision; when the lock's re-check no longer matches, no row comes back and no source goes in.
        session = _store_session(
            active=3,
            facts=[_existing_fact("active")],
            fact_lock=None,
            inserts=[],
        )

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="room-1", user_message_id=8
        )

        self.assertEqual(saved, [])
        self.assertEqual(session.execute.await_count, 3)

    async def test_store_extracted_still_saves_the_fact_when_its_source_cannot_be_stored(self):
        # 回答の後の抽出の間にルームが消えると出典の INSERT が外部キー違反になる。事実の保存は巻き戻さず、出典だけ諦める。
        # If the room is deleted while post-reply extraction runs, the source INSERT violates a foreign key; the fact stays saved.
        savepoints = []
        session = _store_session(
            active=3,
            inserts=[
                _result(mapping=_fact(id=41)),
                IntegrityError("INSERT INTO context_fact_sources", {}, Exception("foreign key violation")),
            ],
        )
        session.begin_nested = MagicMock(side_effect=lambda: savepoints.append(_Savepoint()) or savepoints[-1])

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="gone-room", user_message_id=8
        )

        self.assertEqual([fact["id"] for fact in saved], [41])
        self.assertEqual(len(savepoints), 1)
        self.assertTrue(savepoints[0].rolled_back)
        # 失敗した出典の後に、刈り込みなどを続けない。
        # Nothing more runs after the failed source write.
        self.assertEqual(session.execute.await_count, 5)

    async def test_store_extracted_adds_no_source_when_the_match_is_not_an_active_fact(self):
        cases = {
            "deprecated fact": {"facts": [_existing_fact("deprecated")]},
            "rejected candidate": {"candidates": [self._rejected_candidate()]},
        }
        for name, existing in cases.items():
            with self.subTest(name):
                session = _store_session(active=3, inserts=[], **existing)

                saved = await ContextFactCandidateRepository(session).store_extracted(
                    7, [_extracted()], room_id="room-1", user_message_id=8
                )

                self.assertEqual(saved, [])
                self.assertEqual(session.execute.await_count, 3)

    async def test_store_extracted_adds_no_source_for_a_duplicate_inside_the_same_batch(self):
        # 同じ発話から同じ内容が 2 件返っても、2 件目は先に保存した事実と重複するだけで出典は二重に入らない。
        # Two identical results from one message: the second matches the first candidate, which has no fact id yet.
        session = _store_session(
            active=3,
            inserts=[_result(mapping=_fact(id=41)), _result(inserted_id=70), MagicMock()],
        )

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted(), _extracted(fingerprint="c" * 64)], room_id="room-1", user_message_id=8
        )

        self.assertEqual(len(saved), 1)
        sources = [sql for sql in _executed_sql(session) if sql.startswith("INSERT INTO context_fact_sources")]
        self.assertEqual(len(sources), 1)

    async def test_store_extracted_never_compares_facts_replaced_by_a_newer_fact(self):
        # 置き換えで無効化した事実(superseded)は比較対象に入らないので、本人が元の内容に戻したら(東京→大阪→東京)保存できる。
        # 比較対象は理由が NULL か user の無効化済みの事実と有効な事実だけで、理由 superseded・capacity・merged は条件に現れない。
        # A fact deprecated by replacement (superseded) is not compared, so going back to the old content (Tokyo -> Osaka -> Tokyo)
        # can be saved. Only active facts and facts with a NULL or user reason are compared; superseded, capacity and merged never
        # appear in the condition.
        session = _store_session(active=3, facts=[], inserts=[_result(mapping=_fact(id=41))])

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual([fact["id"] for fact in saved], [41])
        facts_query = _executed(session)[1]
        self.assertEqual(set(facts_query.params.values()), {7, "active", "user"})
        self.assertNotIn("superseded", facts_query.params.values())
        self.assertIn("context_facts.deprecated_reason IS NULL OR context_facts.deprecated_reason = ", str(facts_query))

    async def test_store_extracted_supersedes_the_target_without_a_capacity_replacement(self):
        # 上限でも、置き換えは対象の無効化→新しい事実の挿入→対象への置き換え先の記録の順で、有効件数が変わらないので
        # 別の事実の入れ替え(capacity)は起こさない。
        # Even at the cap a supersede runs: deprecate the target, insert the new fact, record the replacement on the target. The
        # active count does not change, so no other fact is replaced (capacity).
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS,
            inserts=[_result(inserted_id=12), _result(mapping=_fact(id=41)), MagicMock()],
        )
        plans = {0: CandidatePlan(resolution=ReconcileResolution("supersede", 12, 3))}

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()], plans=plans)

        self.assertEqual([fact["id"] for fact in saved], [41])
        statements = _executed(session)
        self.assertEqual(len(statements), 6)
        deprecate, insert, link = statements[3:]
        self.assertTrue(str(deprecate).startswith("UPDATE context_facts SET"))
        self.assertEqual(deprecate.params["status"], "deprecated")
        self.assertEqual(deprecate.params["deprecated_reason"], "superseded")
        self.assertIn("revision=(context_facts.revision + ", str(deprecate).replace(" = ", "="))
        # 判定の時点の revision(3)のままの、本人の有効な事実だけを無効化する。
        # Only the owner's active fact still at the revision it was judged at (3) is deprecated.
        self.assertEqual(deprecate.params["id_1"], 12)
        self.assertEqual(deprecate.params["user_id_1"], 7)
        self.assertEqual(deprecate.params["status_1"], "active")
        self.assertEqual(deprecate.params["revision_2"], 3)
        self.assertTrue(str(insert).startswith("INSERT INTO context_facts"))
        self.assertTrue(str(link).startswith("UPDATE context_facts SET"))
        self.assertEqual(link.params["superseded_by_fact_id"], 41)
        self.assertEqual(link.params["id_1"], 12)
        self.assertEqual(link.params["user_id_1"], 7)
        self.assertFalse(any("FOR UPDATE" in str(statement) for statement in statements))
        self.assertFalse(any(statement.params.get("deprecated_reason") == "capacity" for statement in statements))
        self.assertFalse(any(str(statement).startswith("DELETE") for statement in statements))

    async def test_store_extracted_supersede_keeps_the_new_fact_unconfirmed_and_records_its_source(self):
        session = _store_session(
            active=3,
            inserts=[_result(inserted_id=12), _result(mapping=_fact(id=41)), MagicMock(), _result(inserted_id=70), MagicMock()],
        )
        plans = {0: CandidatePlan(resolution=ReconcileResolution("supersede", 12, 3))}

        await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="room-1", user_message_id=8, plans=plans
        )

        statements = _executed(session)
        insert = statements[4]
        self.assertNotIn("last_confirmed_at", insert.params)
        self.assertEqual(insert.params["source_kind"], "chat")
        self.assertTrue(str(statements[5]).startswith("UPDATE context_facts"))
        self.assertTrue(str(statements[6]).startswith("INSERT INTO context_fact_sources"))
        self.assertIn(41, statements[6].params.values())

    async def test_store_extracted_saves_as_a_new_fact_when_the_target_changed_after_it_was_judged(self):
        # 対象の更新が 0 行(判定の後に編集・無効化された)なら置き換えず、新しい事実として保存する。上限なら通常の入れ替えを行う。
        # With zero rows updated (the target was edited or deprecated after the judgement) nothing is replaced and the content is
        # saved as a new fact, going through the usual replacement at the cap.
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS,
            inserts=[_nothing_replaceable(), _replaced(5), _result(mapping=_fact(id=41))],
        )
        plans = {0: CandidatePlan(resolution=ReconcileResolution("supersede", 12, 3))}

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()], plans=plans)

        self.assertEqual([fact["id"] for fact in saved], [41])
        statements = _executed(session)
        self.assertEqual(statements[3].params["deprecated_reason"], "superseded")
        self.assertEqual(statements[4].params["deprecated_reason"], "capacity")
        self.assertTrue(str(statements[5]).startswith("INSERT INTO context_facts"))
        self.assertFalse(any("superseded_by_fact_id" in statement.params for statement in statements))

    async def test_store_extracted_supersede_does_not_free_a_slot_for_the_next_candidate(self):
        # 上限(空き 0)で、1 件目は置き換え、2 件目は通常の追加。置き換えは有効件数を変えないので、2 件目は入れ替えを必要とする。
        # At the cap (no free slot), the first candidate supersedes and the second is a plain add. A supersede leaves the active
        # count unchanged, so the second still needs a replacement.
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS,
            inserts=[
                _result(inserted_id=12),
                _result(mapping=_fact(id=41)),
                MagicMock(),
                _replaced(5),
                _result(mapping=_fact(id=42)),
            ],
        )
        plans = {0: CandidatePlan(resolution=ReconcileResolution("supersede", 12, 3))}

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7,
            [_extracted(), _extracted(title="Go", content="Writes services in Go", fingerprint="c" * 64)],
            plans=plans,
        )

        self.assertEqual([fact["id"] for fact in saved], [41, 42])
        statements = _executed(session)
        self.assertEqual(statements[6].params["deprecated_reason"], "capacity")
        # 入れ替えの対象から、置き換えて保存したばかりの 41 を外す。
        # The replacement excludes fact 41, which was just saved by the supersede.
        self.assertIn(41, statements[6].params["id_1"])

    async def test_store_extracted_supersede_with_a_free_slot_leaves_the_slot_for_the_next_candidate(self):
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS - 1,
            inserts=[
                _result(inserted_id=12),
                _result(mapping=_fact(id=41)),
                MagicMock(),
                _result(mapping=_fact(id=42)),
            ],
        )
        plans = {0: CandidatePlan(resolution=ReconcileResolution("supersede", 12, 3))}

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7,
            [_extracted(), _extracted(title="Go", content="Writes services in Go", fingerprint="c" * 64)],
            plans=plans,
        )

        self.assertEqual([fact["id"] for fact in saved], [41, 42])
        self.assertFalse(any(statement.params.get("deprecated_reason") == "capacity" for statement in _executed(session)))

    async def test_store_extracted_mention_adds_a_source_to_the_target_and_saves_no_fact(self):
        session = _store_session(active=3, fact_lock=12, inserts=[_result(inserted_id=70), MagicMock()])
        plans = {0: CandidatePlan(resolution=ReconcileResolution("mention", 12, 3))}

        saved = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="room-1", user_message_id=8, plans=plans
        )

        self.assertEqual(saved, [])
        # 再言及と同じく、判定の時点の revision(3)の有効な本人の事実だけを FOR SHARE でロックしてから出典を入れる。
        # Like any re-mention, the source goes in after locking FOR SHARE the owner's active fact at the revision it was judged at (3).
        lock = session.scalar.await_args_list[-1].args[0].compile(dialect=dialect())
        self.assertIn("FOR SHARE", str(lock))
        self.assertEqual({12, 7, 3, "active"}, set(lock.params.values()))
        statements = _executed_sql(session)
        self.assertEqual(len(statements), 5)
        self.assertTrue(statements[3].startswith("INSERT INTO context_fact_sources"))
        self.assertFalse(any(sql.startswith(("UPDATE context_facts", "INSERT INTO context_facts")) for sql in statements))

    async def test_store_extracted_skip_saves_nothing(self):
        session = _store_session(active=3, inserts=[])
        plans = {0: CandidatePlan(resolution=ReconcileResolution("skip", 12, 3))}

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()], plans=plans)

        self.assertEqual(saved, [])
        self.assertEqual(session.execute.await_count, 3)

    async def test_store_extracted_does_not_replace_what_a_mention_just_re_mentioned(self):
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS,
            fact_lock=12,
            inserts=[
                _result(inserted_id=70),
                MagicMock(),
                _replaced(5),
                _result(mapping=_fact(id=41)),
                _result(inserted_id=71),
                MagicMock(),
            ],
        )
        plans = {0: CandidatePlan(resolution=ReconcileResolution("mention", 12, 3))}

        await ContextFactCandidateRepository(session).store_extracted(
            7,
            [_extracted(), _extracted(title="Go", content="Writes services in Go", fingerprint="c" * 64)],
            room_id="room-1",
            user_message_id=8,
            plans=plans,
        )

        replacement = next(
            statement
            for statement in _executed(session)
            if str(statement).startswith("UPDATE context_facts") and statement.params.get("deprecated_reason") == "capacity"
        )
        self.assertIn(12, replacement.params["id_1"])

    async def test_store_extracted_applies_a_plan_only_to_candidates_that_pass_the_duplicate_checks(self):
        # BM25 で既存の事実と重複した候補と、却下済みの fingerprint の候補には、照合の結果を適用しない。
        # A candidate that duplicates an existing fact by BM25, or matches a rejected fingerprint, gets no reconciliation result.
        duplicate = _store_session(
            active=3,
            facts=[_existing_fact("deprecated")],
            inserts=[],
        )
        plans = {0: CandidatePlan(resolution=ReconcileResolution("supersede", 99, 1))}

        await ContextFactCandidateRepository(duplicate).store_extracted(7, [_extracted()], plans=plans)

        self.assertFalse(any(sql.startswith("UPDATE context_facts") for sql in _executed_sql(duplicate)))
        rejected = _store_session(active=3, fingerprint_hit=99, inserts=[])

        await ContextFactCandidateRepository(rejected).store_extracted(7, [_extracted()], plans=plans)

        self.assertEqual(rejected.execute.await_count, 3)

    async def test_store_extracted_stores_the_reconciliation_embedding_with_the_new_fact(self):
        session = _store_session(active=3, inserts=[_result(mapping=_fact(id=41, embedding_status="ready"))])
        plans = {0: CandidatePlan(embedding=[0.25] * 768)}

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()], plans=plans)

        insert = _executed(session)[-1]
        self.assertEqual(insert.params["embedding_vector"], [0.25] * 768)
        self.assertEqual(insert.params["embedding_status"], "ready")
        # 呼び出し側が保存後の予約を省けるよう、保存した事実の埋め込みの状態を返す。
        # The saved fact reports its embedding status so the caller can skip scheduling one after the save.
        self.assertEqual(saved[0]["embedding_status"], "ready")

    async def test_store_extracted_without_a_plan_leaves_the_embedding_to_be_generated_later(self):
        session = _store_session(active=3, inserts=[_result(mapping=_fact(id=41))])

        saved = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        insert = _executed(session)[-1]
        self.assertNotIn("embedding_vector", insert.params)
        self.assertNotIn("embedding_status", insert.params)
        self.assertEqual(saved[0]["embedding_status"], "pending")

    async def test_store_extracted_reuses_the_embedding_for_a_candidate_added_after_a_failed_supersede(self):
        session = _store_session(
            active=3,
            inserts=[_nothing_replaceable(), _result(mapping=_fact(id=41, embedding_status="ready"))],
        )
        plans = {0: CandidatePlan(embedding=[0.5] * 768, resolution=ReconcileResolution("supersede", 12, 3))}

        await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()], plans=plans)

        self.assertEqual(_executed(session)[-1].params["embedding_vector"], [0.5] * 768)

    async def test_get_extraction_settings_is_disabled_when_the_user_row_cannot_be_read(self):
        # 列は NOT NULL。None は行が読めないときだけなので、有効扱いにせず抽出が走らない側へ倒す。
        # The column is NOT NULL, so None means the row could not be read; it must not count as enabled.
        session = MagicMock()
        session.scalar = AsyncMock(side_effect=[None, False, True])
        repo = ContextFactCandidateRepository(session)

        self.assertFalse(await repo.get_extraction_settings(7))
        self.assertFalse(await repo.get_extraction_settings(7))
        self.assertTrue(await repo.get_extraction_settings(7))


if __name__ == "__main__":
    unittest.main()
