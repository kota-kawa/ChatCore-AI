import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect

from services.api_errors import ApiServiceError
from services.repositories.context_fact_repository import (
    MAX_ACTIVE_CONTEXT_FACTS,
    ContextFactRepository,
)


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


def _sql(statement):
    # RETURNING は全列を読み戻すので、書き込み側の文だけを見る
    # RETURNING reads every column back, so look at the writing part of the statement only.
    return " ".join(str(statement.compile(dialect=dialect())).split()).split(" RETURNING")[0]


def _result(*, mapping=None, scalar_rows=None):
    result = MagicMock()
    result.mappings.return_value.first.return_value = mapping
    result.mappings.return_value.all.return_value = [mapping] if mapping else []
    result.scalars.return_value.all.return_value = scalar_rows or []
    return result


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
        compiled = statement.compile(dialect=dialect())
        self.assertIn("embedding_vector <=>", str(compiled))
        self.assertIn(0.4, compiled.params.values())

    async def test_update_fact_uses_optimistic_revision_and_returning(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result(mapping=_fact_row(revision=2)))

        fact = await ContextFactRepository(session).update_fact(
            7,
            10,
            expected_revision=1,
            content="Updated content",
        )

        self.assertEqual(fact["revision"], 2)
        statement = session.execute.await_args.args[0]
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
        await ContextFactRepository(session).update_fact(7, 10, expected_revision=1, **kwargs)
        statement = session.execute.await_args.args[0]
        return _sql(statement), statement.compile(dialect=dialect()).params

    async def test_owner_content_edit_confirms_now(self):
        sql, _ = await self._update(content="New", confirmed_by_owner=True)

        self.assertIn("last_confirmed_at=CURRENT_TIMESTAMP", sql.replace(" ", ""))

    async def test_mcp_content_edit_clears_confirmation(self):
        sql, params = await self._update(content="New")

        self.assertNotIn("last_confirmed_at=CURRENT_TIMESTAMP", sql.replace(" ", ""))
        self.assertIsNone(params["last_confirmed_at"])

    async def test_title_and_type_edits_count_as_content_edits(self):
        _, title_params = await self._update(title="New title")
        _, type_params = await self._update(fact_type="profile")

        self.assertIn("last_confirmed_at", title_params)
        self.assertIn("last_confirmed_at", type_params)

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
