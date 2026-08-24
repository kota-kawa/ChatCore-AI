import unittest
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
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


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


if __name__ == "__main__":
    unittest.main()
