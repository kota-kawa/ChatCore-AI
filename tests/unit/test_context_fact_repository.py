import unittest
from datetime import datetime

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.error_messages import (
    ERROR_CONTEXT_FACT_LIMIT_REACHED,
    ERROR_CONTEXT_FACT_NOT_FOUND,
    ERROR_CONTEXT_FACT_REVISION_CONFLICT,
)
from services.repositories.context_fact_repository import (
    MAX_ACTIVE_CONTEXT_FACTS,
    ContextFactRepository,
)


class FakeCursor:
    def __init__(self, *, fetchone_results=None, fetchall_results=None):
        self._fetchone_results = list(fetchone_results or [])
        self._fetchall_results = list(fetchall_results or [])
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        return self._fetchone_results.pop(0) if self._fetchone_results else None

    def fetchall(self):
        return self._fetchall_results.pop(0) if self._fetchall_results else []

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


def _fact_row(
    *,
    fact_id=10,
    idempotency_key_hash=None,
    idempotency_payload_hash=None,
    importance=80,
):
    now = datetime(2026, 7, 20, 12, 0, 0)
    return (
        fact_id,
        7,
        "project",
        "Chat-Core",
        "Context vault foundation",
        "mcp",
        "conversation:123",
        "client-abc",
        importance,
        idempotency_key_hash,
        idempotency_payload_hash,
        "active",
        1,
        now,
        now,
    )


def _make_repo(cursor):
    connection = FakeConnection(cursor)
    repository = ContextFactRepository(
        connection_getter=lambda: connection,
        retryable_error_checker=lambda _exc: False,
        rollback=lambda conn: conn.rollback() or True,
        sleep=lambda _seconds: None,
    )
    return repository, connection


class ContextFactRepositoryTestCase(unittest.TestCase):
    def test_create_fact_serializes_provenance_and_locks_before_count(self):
        key_hash = "a" * 64
        payload_hash = "c" * 64
        row = _fact_row(
            idempotency_key_hash=key_hash,
            idempotency_payload_hash=payload_hash,
        )
        cursor = FakeCursor(fetchone_results=[None, (3,), row])
        repository, connection = _make_repo(cursor)

        fact = repository.create_fact(
            7,
            fact_type="project",
            title="Chat-Core",
            content="Context vault foundation",
            source_kind="mcp",
            source_ref="conversation:123",
            source_client_id="client-abc",
            importance=80,
            idempotency_key_hash=key_hash,
            idempotency_payload_hash=payload_hash,
        )

        self.assertIn("pg_advisory_xact_lock", cursor.executed[0][0])
        self.assertIn("idempotency_key_hash = %s", cursor.executed[1][0])
        self.assertTrue(cursor.executed[2][0].startswith("SELECT COUNT(*)"))
        self.assertTrue(cursor.executed[3][0].startswith("INSERT INTO context_facts"))
        self.assertEqual(fact["source_kind"], "mcp")
        self.assertEqual(fact["source_ref"], "conversation:123")
        self.assertEqual(fact["source_client_id"], "client-abc")
        self.assertEqual(fact["importance"], 80)
        self.assertEqual(fact["idempotency_key_hash"], key_hash)
        self.assertEqual(fact["idempotency_payload_hash"], payload_hash)
        self.assertTrue(connection.committed)

    def test_create_fact_returns_existing_idempotent_result_before_limit_check(self):
        key_hash = "b" * 64
        payload_hash = "d" * 64
        cursor = FakeCursor(
            fetchone_results=[
                _fact_row(
                    fact_id=22,
                    idempotency_key_hash=key_hash,
                    idempotency_payload_hash=payload_hash,
                )
            ]
        )
        repository, _ = _make_repo(cursor)

        fact = repository.create_fact(
            7,
            fact_type="project",
            title="Chat-Core",
            content="Context vault foundation",
            idempotency_key_hash=key_hash,
            idempotency_payload_hash=payload_hash,
        )

        self.assertEqual(fact["id"], 22)
        self.assertEqual(len(cursor.executed), 2)
        self.assertFalse(any("COUNT(*)" in sql for sql, _ in cursor.executed))
        self.assertFalse(any(sql.startswith("INSERT") for sql, _ in cursor.executed))

    def test_create_fact_rejects_reused_key_with_different_payload(self):
        key_hash = "e" * 64
        cursor = FakeCursor(
            fetchone_results=[
                _fact_row(
                    idempotency_key_hash=key_hash,
                    idempotency_payload_hash="f" * 64,
                )
            ]
        )
        repository, connection = _make_repo(cursor)

        with self.assertRaises(ApiServiceError) as error:
            repository.create_fact(
                7,
                fact_type="project",
                title="Chat-Core",
                content="Different payload",
                idempotency_key_hash=key_hash,
                idempotency_payload_hash="0" * 64,
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertTrue(connection.rolled_back)

    def test_create_fact_checks_active_limit_while_holding_user_lock(self):
        cursor = FakeCursor(fetchone_results=[(MAX_ACTIVE_CONTEXT_FACTS,)])
        repository, connection = _make_repo(cursor)

        with self.assertRaises(ApiServiceError) as error:
            repository.create_fact(
                7,
                fact_type="preference",
                title="Editor",
                content="Uses vim",
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.message, ERROR_CONTEXT_FACT_LIMIT_REACHED)
        self.assertIn("pg_advisory_xact_lock", cursor.executed[0][0])
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_digest_orders_facts_by_importance_then_recency(self):
        cursor = FakeCursor(fetchall_results=[[_fact_row()]])
        repository, _ = _make_repo(cursor)

        facts = repository.list_active_for_digest(7)

        self.assertEqual(len(facts), 1)
        self.assertIn(
            "ORDER BY importance DESC, updated_at DESC, id DESC",
            cursor.executed[0][0],
        )

    def test_reactivation_locks_before_reading_status_and_count(self):
        row = _fact_row()
        cursor = FakeCursor(fetchone_results=[("deprecated",), (2,), row])
        repository, _ = _make_repo(cursor)

        fact = repository.update_fact(
            7,
            10,
            expected_revision=1,
            status="active",
            importance=95,
        )

        self.assertIn("pg_advisory_xact_lock", cursor.executed[0][0])
        self.assertIn("SELECT status FROM context_facts", cursor.executed[1][0])
        self.assertTrue(cursor.executed[2][0].startswith("SELECT COUNT(*)"))
        self.assertTrue(cursor.executed[3][0].startswith("UPDATE context_facts"))
        self.assertIn("importance = %s", cursor.executed[3][0])
        self.assertEqual(cursor.executed[3][1][:2], ("active", 95))
        self.assertEqual(fact["status"], "active")

    def test_reactivation_rejects_active_limit_while_holding_user_lock(self):
        cursor = FakeCursor(
            fetchone_results=[("deprecated",), (MAX_ACTIVE_CONTEXT_FACTS,)]
        )
        repository, connection = _make_repo(cursor)

        with self.assertRaises(ApiServiceError) as error:
            repository.update_fact(
                7,
                10,
                expected_revision=1,
                status="active",
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.message, ERROR_CONTEXT_FACT_LIMIT_REACHED)
        self.assertIn("pg_advisory_xact_lock", cursor.executed[0][0])
        self.assertFalse(any(sql.startswith("UPDATE") for sql, _ in cursor.executed))
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_update_fact_distinguishes_not_found_from_revision_conflict(self):
        not_found_cursor = FakeCursor(fetchone_results=[None, None])
        not_found_repository, not_found_connection = _make_repo(not_found_cursor)

        with self.assertRaises(ResourceNotFoundError) as not_found_error:
            not_found_repository.update_fact(
                7,
                10,
                expected_revision=3,
                title="Updated title",
            )

        self.assertEqual(not_found_error.exception.message, ERROR_CONTEXT_FACT_NOT_FOUND)
        self.assertTrue(not_found_connection.rolled_back)

        conflict_cursor = FakeCursor(fetchone_results=[None, (1,)])
        conflict_repository, conflict_connection = _make_repo(conflict_cursor)

        with self.assertRaises(ApiServiceError) as conflict_error:
            conflict_repository.update_fact(
                7,
                10,
                expected_revision=3,
                title="Updated title",
            )

        self.assertEqual(conflict_error.exception.status_code, 409)
        self.assertEqual(
            conflict_error.exception.message,
            ERROR_CONTEXT_FACT_REVISION_CONFLICT,
        )
        self.assertTrue(conflict_connection.rolled_back)


if __name__ == "__main__":
    unittest.main()
