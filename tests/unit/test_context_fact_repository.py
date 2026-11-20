"""ContextFactRepository（文脈の事実の作成・検索・更新）の SQL とロック順、上限チェック、
確認日時（confirmation）の扱いを検証するテスト。

Tests ContextFactRepository's SQL and lock ordering, the active-fact cap, and how confirmation timestamps
are written on create and update.
"""

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect

from services.api_errors import ApiServiceError
from services.repositories.context_fact_repository import (
    MAX_ACTIVE_CONTEXT_FACTS,
    ContextFactRepository,
)
from tests.helpers.sql_helpers import bind_statement_parameters


# 日本語: 事実テーブルの 1 行分の辞書を作ります。overrides で項目を差し替えます。
# English: Build one fact-table row dict; overrides replace individual fields.
def _fact_row(**overrides):
    row = {
        "id": 10,
        "user_id": 7,
        "fact_type": "project",
        "title": "Chat-Core",
        "content": "Context vault foundation",
        "source_kind": "mcp",
        "source_ref": "conversation:123",
        "source_client_id": "client-abc",
        "importance": 80,
        "idempotency_key_hash": None,
        "idempotency_payload_hash": None,
        "status": "active",
        "revision": 1,
        "confidence": None,
        "last_confirmed_at": None,
        "deprecated_reason": None,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


# 日本語: SQLAlchemy の文を PostgreSQL 方言の SQL 文字列へコンパイルします。
# English: Compile a SQLAlchemy statement into a PostgreSQL-dialect SQL string.
def _sql(statement):
    # RETURNING は全列を読み戻すので、書き込み側の文だけを見る
    # RETURNING reads every column back, so look at the writing part of the statement only.
    return " ".join(str(statement.compile(dialect=dialect())).split()).split(" RETURNING")[0]


# 日本語: DB の実行結果を模したモックを作ります。
# English: Build a mock of a DB execution result.
def _result(*, mapping=None, scalar_rows=None):
    result = MagicMock()
    result.mappings.return_value.first.return_value = mapping
    result.mappings.return_value.all.return_value = [mapping] if mapping else []
    result.scalars.return_value.all.return_value = scalar_rows or []
    return result


# 日本語: AsyncSession をモックし、作成・検索・更新の SQL とロックの順序を確認します。
# English: Mock the AsyncSession and check the SQL and lock order for create, search and update.
class ContextFactRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_create_fact_locks_checks_cap_and_returns_provenance(self):
        session = MagicMock()
        session.scalar = AsyncMock(side_effect=[None, 0])
        session.execute = AsyncMock(
            side_effect=[MagicMock(), _result(mapping=_fact_row())]
        )
        repo = ContextFactRepository(session)

        fact = await repo.create_fact(
            7,
            fact_type="project",
            title="Chat-Core",
            content="Context vault foundation",
            source_kind="mcp",
            source_ref="conversation:123",
            source_client_id="client-abc",
            importance=80,
        )

        self.assertEqual(fact["source_kind"], "mcp")
        self.assertEqual(fact["importance"], 80)
        self.assertIn(
            "pg_advisory_xact_lock",
            str(session.execute.await_args_list[0].args[0].compile(dialect=dialect())),
        )
        insert_statement = session.execute.await_args_list[1].args[0]
        compiled = insert_statement.compile(dialect=dialect())
        self.assertIn("ON CONFLICT", str(compiled))
        self.assertIn("RETURNING", str(compiled))

    async def test_create_fact_rejects_active_limit_inside_user_lock(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=MAX_ACTIVE_CONTEXT_FACTS)
        session.execute = AsyncMock(return_value=MagicMock())

        with self.assertRaises(ApiServiceError) as error:
            await ContextFactRepository(session).create_fact(
                7,
                fact_type="preference",
                title="Editor",
                content="Uses vim",
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(session.execute.await_count, 1)

    async def test_semantic_search_uses_pgvector_distance_threshold(self):
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=_result(scalar_rows=[_fact_row()])
        )
        repo = ContextFactRepository(session)

        with patch(
            "services.repositories.context_fact_repository.get_semantic_max_distance",
            return_value=0.4,
        ):
            facts = await repo.semantic_search(7, [0.1, 0.2, 0.3], limit=5)

        self.assertEqual(facts[0]["id"], 10)
        statement = session.execute.await_args.args[0]
        self.assertIn("embedding_vector <=>", str(statement.compile(dialect=dialect())))
        # しきい値は数値のまま、埋め込みは vector の文字列表現で束縛される。
        # The threshold stays a number while the embedding is bound in pgvector's text form.
        bound = bind_statement_parameters(statement)
        self.assertIn(0.4, bound.values())
        self.assertEqual(bound["context_query_embedding"], "[0.1,0.2,0.3]")

    async def test_reconcile_neighbors_query_is_owner_scoped_bounded_and_ordered_by_distance(self):
        row = {"id": 10, "revision": 2, "fact_type": "profile", "title": "Home", "content": "Lives in Tokyo", "status": "active"}
        result = MagicMock()
        result.mappings.return_value.all.return_value = [row]
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)

        neighbors = await ContextFactRepository(session).find_reconcile_neighbors(
            7, [0.1, 0.2, 0.3], limit=5, max_distance=0.6
        )

        self.assertEqual(neighbors, [row])
        statement = session.execute.await_args.args[0]
        sql = " ".join(str(statement.compile(dialect=dialect())).split())
        # 利用者で絞り、埋め込みのある行だけを、距離の上限以内で近い順に limit 件まで読む。
        # Scoped to the owner, only rows with an embedding, within the distance ceiling, nearest first, at most limit rows.
        self.assertIn("WHERE context_facts.user_id = %(user_id_1)s AND (", sql)
        self.assertIn("context_facts.embedding_vector IS NOT NULL", sql)
        self.assertIn("(context_facts.embedding_vector <=> %(context_query_embedding)s) <= %(param_1)s", sql)
        self.assertIn("ORDER BY context_facts.embedding_vector <=> %(context_query_embedding)s LIMIT %(param_2)s", sql)
        bound = bind_statement_parameters(statement)
        self.assertEqual(bound["user_id_1"], 7)
        self.assertEqual(bound["param_1"], 0.6)
        self.assertEqual(bound["param_2"], 5)
        self.assertEqual(bound["context_query_embedding"], "[0.1,0.2,0.3]")
        # 最後に話題に出た時刻は、出典の最大値(無ければ作成時刻)から読む。
        # When it was last mentioned is read from the newest source (or the creation time without one).
        self.assertIn("max(context_fact_sources.observed_at)", sql)
        self.assertIn("AS last_mentioned", sql)

    async def test_get_reconcile_facts_reads_only_the_given_owner_facts_the_comparison_can_see(self):
        row = {"id": 10, "revision": 2, "fact_type": "profile", "title": "Home", "content": "Lives in Tokyo", "status": "active"}
        result = MagicMock()
        result.mappings.return_value.all.return_value = [row]
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)

        facts = await ContextFactRepository(session).get_reconcile_facts(7, [10, 11])

        self.assertEqual(facts, [row])
        statement = session.execute.await_args.args[0]
        sql = " ".join(str(statement.compile(dialect=dialect())).split())
        self.assertIn("context_facts.user_id = %(user_id_1)s AND context_facts.id IN (", sql)
        self.assertIn("context_facts.deprecated_reason IS NULL OR context_facts.deprecated_reason = ", sql)
        self.assertIn("AS last_mentioned", sql)
        # 埋め込みの有無や距離には依らない(BM25 で一致した記憶をそのまま近い記憶に入れるため)。
        # Independent of the embedding or distance (the BM25-matched memory goes into the nearby ones as it is).
        self.assertNotIn("embedding_vector", sql)
        bound = bind_statement_parameters(statement)
        self.assertEqual(bound["user_id_1"], 7)
        self.assertEqual(statement.compile(dialect=dialect()).params["id_1"], [10, 11])

    async def test_reconcile_neighbors_only_target_active_and_owner_deprecated_facts(self):
        # 置き換え(superseded)・上限(capacity)・統合(merged)で無効化した事実は対象にしない。条件は重複判定と同じ
        # matchable_fact_clause（有効、または理由が NULL か user の無効化済み）。
        # Facts deprecated by replacement (superseded), the cap (capacity) or merging (merged) are never targeted. The condition is
        # the one duplicate detection uses (active, or deprecated with a NULL or user reason).
        session = MagicMock()
        result = MagicMock()
        result.mappings.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        await ContextFactRepository(session).find_reconcile_neighbors(7, [0.1], limit=5, max_distance=0.6)

        statement = session.execute.await_args.args[0]
        sql = " ".join(str(statement.compile(dialect=dialect())).split())
        self.assertIn(
            "(context_facts.status = %(status_1)s OR context_facts.deprecated_reason IS NULL OR "
            "context_facts.deprecated_reason = %(deprecated_reason_1)s)",
            sql,
        )
        values = set(bind_statement_parameters(statement).values())
        self.assertTrue({"active", "user"} <= values)
        self.assertFalse({"superseded", "capacity", "merged"} & values)

    async def test_update_fact_uses_optimistic_revision_and_returning(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result(mapping=_fact_row(revision=2)))
        session.scalar = AsyncMock(return_value=True)

        fact = await ContextFactRepository(session).update_fact(
            7,
            10,
            expected_revision=1,
            content="Updated content",
        )

        self.assertEqual(fact["revision"], 2)
        statement = session.execute.await_args_list[0].args[0]
        compiled = statement.compile(dialect=dialect())
        self.assertIn("revision =", str(compiled))
        self.assertIn("RETURNING", str(compiled))

    async def test_reactivation_holds_lock_before_status_and_count(self):
        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=[MagicMock(), _result(mapping=_fact_row(status="active"))]
        )
        session.scalar = AsyncMock(side_effect=["deprecated", 0])

        fact = await ContextFactRepository(session).update_fact(
            7,
            10,
            expected_revision=1,
            status="active",
        )

        self.assertEqual(fact["status"], "active")
        self.assertIn(
            "pg_advisory_xact_lock",
            str(session.execute.await_args_list[0].args[0].compile(dialect=dialect())),
        )


# 日本語: 書き込み元（本人の画面、MCP、インポート）ごとに、確認日時と confidence を記録するか消すかを確認します。
# English: Check, per write origin (owner UI, MCP, import), whether confirmation time and confidence are recorded
# or cleared.
class ContextFactConfirmationTestCase(unittest.IsolatedAsyncioTestCase):
    async def _create(self, source_kind):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=0)
        session.execute = AsyncMock(side_effect=[MagicMock(), _result(mapping=_fact_row())])
        await ContextFactRepository(session).create_fact(
            7,
            fact_type="preference",
            title="Editor",
            content="Uses vim",
            source_kind=source_kind,
        )
        return session.execute.await_args_list[1].args[0]

    async def test_manual_create_is_confirmed_now(self):
        statement = await self._create("manual")

        self.assertIn("CURRENT_TIMESTAMP", _sql(statement))
        self.assertNotIn("last_confirmed_at", statement.compile(dialect=dialect()).params)

    async def test_mcp_create_stays_unconfirmed(self):
        statement = await self._create("mcp")

        self.assertNotIn("CURRENT_TIMESTAMP", _sql(statement))
        self.assertIsNone(statement.compile(dialect=dialect()).params["last_confirmed_at"])

    async def test_import_does_not_write_confirmation_or_confidence(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=0)
        inserted = MagicMock()
        inserted.mappings.return_value.all.return_value = [_fact_row()]
        existing = MagicMock()
        existing.all.return_value = []
        session.execute = AsyncMock(side_effect=[MagicMock(), existing, inserted])
        fact = {
            "fact_type": "preference",
            "title": "Editor",
            "content": "Uses vim",
            "status": "active",
            "importance": 50,
            "confidence": 0.9,
            "last_confirmed_at": "2026-01-01T00:00:00",
        }

        await ContextFactRepository(session).bulk_import_facts(7, [fact])

        insert_sql = _sql(session.execute.await_args_list[-1].args[0])
        self.assertIn("INSERT INTO context_facts", insert_sql)
        self.assertNotIn("last_confirmed_at", insert_sql)
        self.assertNotIn("confidence", insert_sql)

    async def _update(self, **kwargs):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result(mapping=_fact_row(revision=2)))
        session.scalar = AsyncMock(return_value=True)
        await ContextFactRepository(session).update_fact(7, 10, expected_revision=1, **kwargs)
        statement = next(
            call.args[0]
            for call in session.execute.await_args_list
            if str(call.args[0].compile(dialect=dialect())).startswith("UPDATE context_facts")
        )
        return _sql(statement), statement.compile(dialect=dialect()).params

    async def test_owner_content_edit_confirms_now(self):
        sql, _ = await self._update(content="New", confirmed_by_owner=True)

        self.assertIn(
            "CASEWHEN(context_facts.contentISDISTINCTFROM",
            sql.replace(" ", ""),
        )
        self.assertIn("THENCURRENT_TIMESTAMPELSEcontext_facts.last_confirmed_atEND", sql.replace(" ", ""))

    async def test_mcp_content_edit_clears_confirmation(self):
        sql, _ = await self._update(content="New")

        self.assertIn("THENNULL", sql.replace(" ", ""))
        self.assertIn("ELSEcontext_facts.last_confirmed_atEND", sql.replace(" ", ""))

    async def test_resending_unchanged_fact_fields_does_not_confirm_or_reembed(self):
        sql, params = await self._update(
            title="Chat-Core",
            content="Context vault foundation",
            fact_type="project",
            importance=90,
            confirmed_by_owner=True,
        )

        normalized_sql = sql.replace(" ", "")
        self.assertIn("context_facts.titleISDISTINCTFROM", normalized_sql)
        self.assertIn("context_facts.contentISDISTINCTFROM", normalized_sql)
        self.assertIn("context_facts.fact_typeISDISTINCTFROM", normalized_sql)
        self.assertIn("ELSEcontext_facts.last_confirmed_atEND", normalized_sql)
        self.assertIn("ELSEcontext_facts.embedding_statusEND", normalized_sql)
        self.assertEqual(params["title"], "Chat-Core")
        self.assertEqual(params["content"], "Context vault foundation")

    async def test_title_and_type_edits_count_as_content_edits(self):
        title_sql, _ = await self._update(title="New title")
        type_sql, _ = await self._update(fact_type="profile")

        self.assertIn("context_facts.title IS DISTINCT FROM", title_sql)
        self.assertIn("context_facts.fact_type IS DISTINCT FROM", type_sql)

    async def test_status_and_importance_changes_leave_confirmation_alone(self):
        for kwargs in ({"importance": 90}, {"importance": 90, "confirmed_by_owner": True}):
            sql, params = await self._update(**kwargs)
            self.assertNotIn("last_confirmed_at", sql)
            self.assertNotIn("last_confirmed_at", params)

        session = MagicMock()
        session.execute = AsyncMock(return_value=_result(mapping=_fact_row(status="deprecated")))
        await ContextFactRepository(session).update_fact(
            7, 10, expected_revision=1, status="deprecated", confirmed_by_owner=True
        )
        self.assertNotIn("last_confirmed_at", _sql(session.execute.await_args.args[0]))

    async def test_deprecating_records_the_user_reason_and_restoring_clears_it(self):
        deprecate_sql, deprecate_params = await self._update(status="deprecated")
        restore_sql, restore_params = await self._update(status="active")

        self.assertIn("deprecated_reason=", deprecate_sql.replace(" ", ""))
        self.assertEqual(deprecate_params["deprecated_reason"], "user")
        self.assertIn("deprecated_reason=", restore_sql.replace(" ", ""))
        self.assertIsNone(restore_params["deprecated_reason"])

    async def test_status_changes_clear_the_replacement_link_and_other_updates_leave_it(self):
        # 復元だけでなく、置き換えで無効化した事実を本人・MCP が改めて無効化したとき(理由は user に上書きされる)も、
        # 置き換え先を NULL に戻す。状態を変えない更新は触らない。
        # Not only a restore: when the owner or MCP deprecates a fact that a newer one replaced (its reason is overwritten with user),
        # the replacement link is cleared too. Updates that leave the status alone do not touch it.
        for status in ("active", "deprecated"):
            with self.subTest(status=status):
                _, params = await self._update(status=status)

                self.assertIn("superseded_by_fact_id", params)
                self.assertIsNone(params["superseded_by_fact_id"])
        for kwargs in ({"importance": 90}, {"title": "New title"}):
            with self.subTest(kwargs=kwargs):
                _, params = await self._update(**kwargs)
                self.assertNotIn("superseded_by_fact_id", params)

    async def test_updates_that_leave_the_status_alone_keep_the_reason(self):
        for kwargs in ({"importance": 90}, {"title": "New title"}, {"content": "New", "confirmed_by_owner": True}):
            with self.subTest(kwargs=kwargs):
                sql, params = await self._update(**kwargs)
                self.assertNotIn("deprecated_reason", sql)
                self.assertNotIn("deprecated_reason", params)

    # 日本語: 更新で実行された文を、scalar と execute をまたいだ実行順で返します。
    # English: Return the statements a content update ran, in execution order across scalar and execute.
    async def _update_statements(self, *, content_changes=True, **kwargs):
        order = []
        session = MagicMock()

        async def execute(statement):
            order.append(statement)
            return _result(mapping=_fact_row(revision=2))

        async def scalar(statement):
            order.append(statement)
            return content_changes

        session.execute = AsyncMock(side_effect=execute)
        session.scalar = AsyncMock(side_effect=scalar)
        await ContextFactRepository(session).update_fact(7, 10, expected_revision=1, **kwargs)
        return order

    async def test_content_edit_locks_the_row_then_updates_then_deletes_the_fact_sources(self):
        for kwargs in ({"content": "New"}, {"title": "New"}, {"fact_type": "profile"}, {"content": "New", "confirmed_by_owner": True}):
            with self.subTest(kwargs=kwargs):
                statements = await self._update_statements(**kwargs)

                self.assertEqual(len(statements), 3)
                lock_sql = _sql(statements[0])
                # 事実の行を更新と同じ所有者・revision で FOR UPDATE ロックし、「実際に変わる」条件を SQL で判定する。
                # The row is locked FOR UPDATE under the update's owner and revision, and "actually changes" is judged in SQL.
                self.assertTrue(lock_sql.endswith("FOR UPDATE"))
                self.assertIn("IS DISTINCT FROM", lock_sql)
                self.assertIn("context_facts.user_id =", lock_sql)
                self.assertIn("context_facts.revision =", lock_sql)
                self.assertTrue(_sql(statements[1]).startswith("UPDATE context_facts"))
                # 出典の削除は更新の後（行ロックを持ったまま）。
                # The sources are deleted after the update, while the row lock is held.
                self.assertTrue(_sql(statements[2]).startswith("DELETE FROM context_fact_sources WHERE"))
                self.assertIn("context_fact_sources.fact_id =", _sql(statements[2]))

    async def test_resending_unchanged_wording_keeps_the_fact_sources(self):
        statements = await self._update_statements(content_changes=False, content="Context vault foundation")

        self.assertEqual(len(statements), 2)
        self.assertFalse(any("context_fact_sources" in _sql(statement) for statement in statements))

    async def test_a_revision_conflict_deletes_no_sources(self):
        session = MagicMock()
        session.scalar = AsyncMock(side_effect=[None, 10])
        session.execute = AsyncMock(return_value=_result(mapping=None))

        with self.assertRaises(ApiServiceError):
            await ContextFactRepository(session).update_fact(7, 10, expected_revision=1, content="New")

        self.assertFalse(
            any("context_fact_sources" in _sql(call.args[0]) for call in session.execute.await_args_list)
        )

    async def test_edits_that_do_not_change_the_wording_keep_the_fact_sources(self):
        for kwargs in (
            {"importance": 90},
            {"status": "deprecated"},
            {"importance": 90, "confirmed_by_owner": True},
        ):
            with self.subTest(kwargs=kwargs):
                statements = await self._update_statements(**kwargs)

                self.assertEqual(len(statements), 1)
                self.assertNotIn("context_fact_sources", _sql(statements[0]))

        session = MagicMock()
        session.execute = AsyncMock()
        await ContextFactRepository(session).store_embedding(10, [0.1, 0.2], expected_revision=1)
        self.assertNotIn("context_fact_sources", _sql(session.execute.await_args.args[0]))

    async def test_mcp_content_edit_marks_the_fact_as_mcp_sourced(self):
        sql, params = await self._update(content="New")

        self.assertIn("source_kind=CASEWHEN(context_facts.contentISDISTINCTFROM", sql.replace(" ", ""))
        self.assertIn("mcp", params.values())
        self.assertIn("ELSEcontext_facts.source_kindEND", sql.replace(" ", ""))

    async def test_owner_edit_and_non_content_edits_keep_the_source_kind(self):
        for kwargs in ({"content": "New", "confirmed_by_owner": True}, {"importance": 90}, {"status": "deprecated"}):
            with self.subTest(kwargs=kwargs):
                sql, params = await self._update(**kwargs)

                self.assertNotIn("source_kind", sql)
                self.assertNotIn("mcp", params.values())

    async def test_store_embedding_leaves_confirmation_alone(self):
        session = MagicMock()
        session.execute = AsyncMock()

        await ContextFactRepository(session).store_embedding(10, [0.1, 0.2], expected_revision=1)

        self.assertNotIn("last_confirmed_at", _sql(session.execute.await_args.args[0]))

    async def test_owner_touches_advance_the_revision_and_embedding_storage_does_not(self):
        # 上限での入れ替えは「revision が初期値 1 のまま」を手を入れていない印にする。復元・重要度の変更・無効化は
        # last_confirmed_at を変えないが revision を進める。埋め込みの保存は進めない(進めると未編集の事実が対象から外れる)。
        # The cap replacement treats "revision still at its initial 1" as untouched. Restoring, changing importance and
        # deprecating leave last_confirmed_at alone but advance the revision; storing an embedding must not advance it.
        for kwargs in ({"status": "active"}, {"status": "deprecated"}, {"importance": 90}):
            with self.subTest(kwargs=kwargs):
                sql, _ = await self._update(**kwargs)
                self.assertIn("revision=(context_facts.revision+", sql.replace(" ", ""))
                self.assertNotIn("last_confirmed_at", sql)

        session = MagicMock()
        session.execute = AsyncMock()
        await ContextFactRepository(session).store_embedding(10, [0.1, 0.2], expected_revision=1)
        set_clause = _sql(session.execute.await_args.args[0]).split("WHERE")[0]
        self.assertNotIn("revision", set_clause)

    def test_serialization_exposes_confidence_and_confirmation(self):
        fact = ContextFactRepository._serialize_row(
            _fact_row(confidence=0.8, last_confirmed_at=datetime(2026, 9, 1, 12, 0))
        )

        self.assertEqual(fact["confidence"], 0.8)
        self.assertEqual(fact["last_confirmed_at"], "2026-09-01T12:00:00")
        unconfirmed = ContextFactRepository._serialize_row(_fact_row())
        self.assertIsNone(unconfirmed["confidence"])
        self.assertIsNone(unconfirmed["last_confirmed_at"])


if __name__ == "__main__":
    unittest.main()
