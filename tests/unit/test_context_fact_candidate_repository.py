import unittest
from datetime import datetime

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.error_messages import (
    ERROR_CONTEXT_FACT_CANDIDATE_NOT_FOUND,
    ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
    ERROR_CONTEXT_FACT_LIMIT_REACHED,
)
from services.repositories.context_fact_candidate_repository import (
    MAX_PENDING_CONTEXT_FACT_CANDIDATES,
    ContextFactCandidateRepository,
)
from services.repositories.context_fact_repository import MAX_ACTIVE_CONTEXT_FACTS


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


def _candidate_row(*, status="pending", revision=1, promoted_fact_id=None, candidate_id=8):
    now = datetime(2026, 7, 23, 12, 0, 0)
    return (
        candidate_id,
        7,
        "project",
        "Chat-Core",
        "Phase 2 candidate",
        "chat",
        "room-123",
        None,
        80,
        0.9,
        status,
        "a" * 64,
        promoted_fact_id,
        revision,
        now,
        now,
    )


def _fact_row(*, fact_id=31):
    now = datetime(2026, 7, 23, 12, 0, 0)
    return (
        fact_id,
        7,
        "project",
        "Edited title",
        "Edited content",
        "chat",
        "room-123",
        None,
        95,
        None,
        None,
        "active",
        1,
        now,
        now,
    )


def _make_repository(cursor):
    connection = FakeConnection(cursor)
    repository = ContextFactCandidateRepository(
        connection_getter=lambda: connection,
        retryable_error_checker=lambda _exc: False,
        rollback=lambda conn: conn.rollback() or True,
        sleep=lambda _seconds: None,
    )
    return repository, connection


def _prepared_candidate(fingerprint):
    return {
        "fact_type": "project",
        "title": "Chat-Core",
        "content": "Phase 2 candidate",
        "source_kind": "chat",
        "source_ref": "room-123",
        "importance": 80,
        "confidence": 0.9,
        "fingerprint": fingerprint,
    }


class ContextFactCandidateRepositoryTestCase(unittest.TestCase):
    def test_store_candidates_locks_caps_and_skips_duplicates_across_history(self):
        cursor = FakeCursor(fetchone_results=[(98,), None, (11,), (12,)])
        repository, connection = _make_repository(cursor)

        inserted = repository.store_candidates(
            7,
            [
                _prepared_candidate("a" * 64),
                _prepared_candidate("b" * 64),
                _prepared_candidate("c" * 64),
            ],
        )

        self.assertEqual(inserted, 2)
        self.assertIn("pg_advisory_xact_lock", cursor.executed[0][0])
        insert_statements = [sql for sql, _ in cursor.executed if sql.startswith("INSERT")]
        self.assertEqual(len(insert_statements), 3)
        self.assertTrue(all("WHERE NOT EXISTS" in sql for sql in insert_statements))
        self.assertTrue(all("fingerprint = %s" in sql for sql in insert_statements))
        self.assertTrue(connection.committed)

    def test_store_candidates_does_not_insert_when_pending_queue_is_full(self):
        cursor = FakeCursor(fetchone_results=[(MAX_PENDING_CONTEXT_FACT_CANDIDATES,)])
        repository, connection = _make_repository(cursor)

        inserted = repository.store_candidates(7, [_prepared_candidate("a" * 64)])

        self.assertEqual(inserted, 0)
        self.assertEqual(len(cursor.executed), 2)
        self.assertTrue(connection.committed)

    def test_approve_candidate_promotes_fact_and_updates_candidate_atomically(self):
        approved = _candidate_row(status="approved", revision=2, promoted_fact_id=31)
        cursor = FakeCursor(
            fetchone_results=[_candidate_row(), (4,), _fact_row(), approved]
        )
        repository, connection = _make_repository(cursor)

        candidate, fact = repository.approve_candidate(
            7,
            8,
            expected_revision=1,
            title="Edited title",
            content="Edited content",
            importance=95,
        )

        self.assertIn("pg_advisory_xact_lock", cursor.executed[0][0])
        self.assertIn("FOR UPDATE", cursor.executed[1][0])
        self.assertTrue(cursor.executed[3][0].startswith("INSERT INTO context_facts"))
        self.assertIn("status = 'approved'", cursor.executed[4][0])
        self.assertEqual(cursor.executed[4][1], (31, 8, 7, 1))
        self.assertEqual(candidate["status"], "approved")
        self.assertEqual(fact["id"], 31)
        self.assertTrue(connection.committed)

    def test_approve_candidate_rejects_stale_revision_before_fact_insert(self):
        cursor = FakeCursor(fetchone_results=[_candidate_row(revision=2)])
        repository, connection = _make_repository(cursor)

        with self.assertRaises(ApiServiceError) as error:
            repository.approve_candidate(7, 8, expected_revision=1)

        self.assertEqual(
            error.exception.message,
            ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
        )
        self.assertFalse(any(sql.startswith("INSERT") for sql, _ in cursor.executed))
        self.assertTrue(connection.rolled_back)

    def test_approve_candidate_enforces_active_fact_limit(self):
        cursor = FakeCursor(
            fetchone_results=[_candidate_row(), (MAX_ACTIVE_CONTEXT_FACTS,)]
        )
        repository, connection = _make_repository(cursor)

        with self.assertRaises(ApiServiceError) as error:
            repository.approve_candidate(7, 8, expected_revision=1)

        self.assertEqual(error.exception.message, ERROR_CONTEXT_FACT_LIMIT_REACHED)
        self.assertFalse(any(sql.startswith("INSERT") for sql, _ in cursor.executed))
        self.assertTrue(connection.rolled_back)

    def test_reject_candidate_distinguishes_not_found_and_conflict(self):
        missing_cursor = FakeCursor(fetchone_results=[None, None])
        missing_repository, _ = _make_repository(missing_cursor)
        with self.assertRaises(ResourceNotFoundError) as missing_error:
            missing_repository.reject_candidate(7, 8, expected_revision=1)
        self.assertEqual(
            missing_error.exception.message,
            ERROR_CONTEXT_FACT_CANDIDATE_NOT_FOUND,
        )

        conflict_cursor = FakeCursor(fetchone_results=[None, (1,)])
        conflict_repository, _ = _make_repository(conflict_cursor)
        with self.assertRaises(ApiServiceError) as conflict_error:
            conflict_repository.reject_candidate(7, 8, expected_revision=1)
        self.assertEqual(
            conflict_error.exception.message,
            ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
        )

    def test_should_extract_context_checks_opt_in_and_capacity_in_one_query(self):
        cursor = FakeCursor(fetchone_results=[(True, True)])
        repository, _ = _make_repository(cursor)

        self.assertTrue(repository.should_extract_context(7))
        self.assertEqual(len(cursor.executed), 1)
        self.assertIn("context_auto_extract_enabled", cursor.executed[0][0])
        self.assertEqual(
            cursor.executed[0][1],
            (MAX_PENDING_CONTEXT_FACT_CANDIDATES, 7),
        )

    def test_extraction_setting_is_false_for_missing_user_and_update_is_scoped(self):
        read_cursor = FakeCursor(fetchone_results=[None])
        read_repository, _ = _make_repository(read_cursor)
        self.assertFalse(read_repository.get_extraction_settings(999))

        update_cursor = FakeCursor(fetchone_results=[(True,)])
        update_repository, connection = _make_repository(update_cursor)
        self.assertTrue(update_repository.update_extraction_settings(7, True))
        self.assertEqual(update_cursor.executed[0][1], (True, 7))
        self.assertTrue(connection.committed)


if __name__ == "__main__":
    unittest.main()
