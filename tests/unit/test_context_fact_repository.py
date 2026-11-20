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
