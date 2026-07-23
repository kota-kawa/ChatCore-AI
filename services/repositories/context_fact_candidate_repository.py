from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.db import Error, get_db_connection, is_retryable_db_error, rollback_connection
from services.error_messages import (
    ERROR_CONTEXT_EXTRACTION_SETTINGS_NOT_FOUND,
    ERROR_CONTEXT_FACT_CANDIDATE_NOT_FOUND,
    ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
    ERROR_CONTEXT_FACT_LIMIT_REACHED,
)
from services.repositories.context_fact_repository import MAX_ACTIVE_CONTEXT_FACTS

DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
MAX_PENDING_CONTEXT_FACT_CANDIDATES = 100

# Share the context-vault lock namespace so fact promotion and direct fact writes
# cannot race past their respective per-user limits.
_CONTEXT_VAULT_LOCK_NAMESPACE = 1129601108  # ASCII "CTXT"

_CANDIDATE_COLUMNS = (
    "id",
    "user_id",
    "fact_type",
    "title",
    "content",
    "source_kind",
    "source_ref",
    "source_client_id",
    "importance",
    "confidence",
    "status",
    "fingerprint",
    "promoted_fact_id",
    "revision",
    "created_at",
    "updated_at",
)
_CANDIDATE_SELECT_COLUMNS = ", ".join(_CANDIDATE_COLUMNS)

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
    "idempotency_key_hash",
    "idempotency_payload_hash",
    "status",
    "revision",
    "created_at",
    "updated_at",
)
_FACT_SELECT_COLUMNS = ", ".join(_FACT_COLUMNS)


class ContextFactCandidateRepository:
    """Owner-scoped persistence for extracted context candidates."""

    def __init__(
        self,
        *,
        connection_getter: Callable[[], Any] = get_db_connection,
        retryable_error_checker: Callable[[BaseException], bool] = is_retryable_db_error,
        rollback: Callable[[Any], bool] = rollback_connection,
        sleep: Callable[[float], Any] = time.sleep,
    ) -> None:
        self._connection_getter = connection_getter
        self._is_retryable_db_error = retryable_error_checker
        self._rollback = rollback
        self._sleep = sleep

    def _run_write(self, operation: Callable[[Any], Any], *, error_message: str) -> Any:
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    result = operation(cursor)
                    conn.commit()
                    return result
                except ApiServiceError:
                    self._rollback(conn)
                    raise
                except Error as exc:
                    self._rollback(conn)
                    if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    self._rollback(conn)
                    raise
                finally:
                    cursor.close()
        raise RuntimeError(error_message)

    @staticmethod
    def _lock_user(cursor: Any, user_id: int) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (_CONTEXT_VAULT_LOCK_NAMESPACE, user_id),
        )

    @staticmethod
    def _serialize_candidate(row: Any) -> dict[str, Any]:
        record = dict(zip(_CANDIDATE_COLUMNS, row))
        return {
            "id": int(record["id"]),
            "user_id": int(record["user_id"]),
            "fact_type": str(record["fact_type"]),
            "title": str(record["title"] or ""),
            "content": str(record["content"] or ""),
            "source_kind": str(record["source_kind"] or "chat"),
            "source_ref": (
                str(record["source_ref"]) if record["source_ref"] is not None else None
            ),
            "source_client_id": (
                str(record["source_client_id"])
                if record["source_client_id"] is not None
                else None
            ),
            "importance": int(record["importance"] if record["importance"] is not None else 50),
            "confidence": float(record["confidence"] or 0),
            "status": str(record["status"] or "pending"),
            "fingerprint": str(record["fingerprint"]),
            "promoted_fact_id": (
                int(record["promoted_fact_id"])
                if record["promoted_fact_id"] is not None
                else None
            ),
            "revision": max(int(record["revision"] or 1), 1),
            "created_at": serialize_datetime_iso(record["created_at"]),
            "updated_at": serialize_datetime_iso(record["updated_at"]),
        }

    @staticmethod
    def _serialize_fact(row: Any) -> dict[str, Any]:
        record = dict(zip(_FACT_COLUMNS, row))
        return {
            "id": int(record["id"]),
            "user_id": int(record["user_id"]),
            "fact_type": str(record["fact_type"]),
            "title": str(record["title"] or ""),
            "content": str(record["content"] or ""),
            "source_kind": str(record["source_kind"] or "chat"),
            "source_ref": (
                str(record["source_ref"]) if record["source_ref"] is not None else None
            ),
            "source_client_id": (
                str(record["source_client_id"])
                if record["source_client_id"] is not None
                else None
            ),
            "importance": int(record["importance"] if record["importance"] is not None else 50),
            "status": str(record["status"] or "active"),
            "revision": max(int(record["revision"] or 1), 1),
            "created_at": serialize_datetime_iso(record["created_at"]),
            "updated_at": serialize_datetime_iso(record["updated_at"]),
        }

    def store_candidates(self, user_id: int, candidates: list[dict[str, Any]]) -> int:
        """Insert unique candidates up to the per-user pending cap."""

        def op(cursor: Any) -> int:
            self._lock_user(cursor, user_id)
            cursor.execute(
                "SELECT COUNT(*) FROM context_fact_candidates "
                "WHERE user_id = %s AND status = 'pending'",
                (user_id,),
            )
            pending_count = int((cursor.fetchone() or [0])[0])
            remaining = max(MAX_PENDING_CONTEXT_FACT_CANDIDATES - pending_count, 0)
            inserted = 0
            for candidate in candidates:
                if inserted >= remaining:
                    break
                cursor.execute(
                    """
                    INSERT INTO context_fact_candidates (
                        user_id, fact_type, title, content, source_kind, source_ref,
                        source_client_id, importance, confidence, fingerprint
                    )
                    SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM context_fact_candidates
                         WHERE user_id = %s AND fingerprint = %s
                    )
                    ON CONFLICT (user_id, fingerprint) WHERE status = 'pending'
                    DO NOTHING
                    RETURNING id
                    """,
                    (
                        user_id,
                        candidate["fact_type"],
                        candidate["title"],
                        candidate["content"],
                        candidate.get("source_kind", "chat"),
                        candidate.get("source_ref"),
                        candidate.get("source_client_id"),
                        candidate.get("importance", 50),
                        candidate.get("confidence", 0),
                        candidate["fingerprint"],
                        user_id,
                        candidate["fingerprint"],
                    ),
                )
                if cursor.fetchone() is not None:
                    inserted += 1
            return inserted

        return self._run_write(op, error_message="Failed to store context fact candidates.")

    def list_candidates(
        self,
        user_id: int,
        *,
        status: str = "pending",
        limit: int = 21,
        before_created_at: datetime | None = None,
        before_id: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions = ["user_id = %s", "status = %s"]
        params: list[Any] = [user_id, status]
        if before_created_at is not None and before_id is not None:
            conditions.append("(created_at, id) < (%s, %s)")
            params.extend([before_created_at, before_id])
        params.append(limit)
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT {_CANDIDATE_SELECT_COLUMNS}
                      FROM context_fact_candidates
                     WHERE {" AND ".join(conditions)}
                     ORDER BY created_at DESC, id DESC
                     LIMIT %s
                    """,
                    tuple(params),
                )
                return [self._serialize_candidate(row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    def count_pending(self, user_id: int) -> int:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM context_fact_candidates "
                    "WHERE user_id = %s AND status = 'pending'",
                    (user_id,),
                )
                return int((cursor.fetchone() or [0])[0])
            finally:
                cursor.close()

    def approve_candidate(
        self,
        user_id: int,
        candidate_id: int,
        *,
        expected_revision: int,
        fact_type: str | None = None,
        title: str | None = None,
        content: str | None = None,
        importance: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Promote a pending candidate and mark it approved atomically."""

        def op(cursor: Any) -> tuple[dict[str, Any], dict[str, Any]]:
            self._lock_user(cursor, user_id)
            cursor.execute(
                f"""
                SELECT {_CANDIDATE_SELECT_COLUMNS}
                  FROM context_fact_candidates
                 WHERE id = %s AND user_id = %s
                 FOR UPDATE
                """,
                (candidate_id, user_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise ResourceNotFoundError(ERROR_CONTEXT_FACT_CANDIDATE_NOT_FOUND)
            candidate = self._serialize_candidate(row)
            if candidate["status"] != "pending" or candidate["revision"] != expected_revision:
                raise ApiServiceError(
                    ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
                    409,
                    status="fail",
                )

            cursor.execute(
                "SELECT COUNT(*) FROM context_facts WHERE user_id = %s AND status = 'active'",
                (user_id,),
            )
            if int((cursor.fetchone() or [0])[0]) >= MAX_ACTIVE_CONTEXT_FACTS:
                raise ApiServiceError(ERROR_CONTEXT_FACT_LIMIT_REACHED, 409, status="fail")

            promoted_fact_type = fact_type if fact_type is not None else candidate["fact_type"]
            promoted_title = title if title is not None else candidate["title"]
            promoted_content = content if content is not None else candidate["content"]
            promoted_importance = (
                importance if importance is not None else candidate["importance"]
            )
            cursor.execute(
                f"""
                INSERT INTO context_facts (
                    user_id, fact_type, title, content, source_kind, source_ref,
                    source_client_id, importance
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_FACT_SELECT_COLUMNS}
                """,
                (
                    user_id,
                    promoted_fact_type,
                    promoted_title,
                    promoted_content,
                    candidate["source_kind"],
                    candidate["source_ref"],
                    candidate["source_client_id"],
                    promoted_importance,
                ),
            )
            fact_row = cursor.fetchone()
            if fact_row is None:  # pragma: no cover - PostgreSQL RETURNING invariant
                raise RuntimeError("Promoted context fact was not returned.")
            fact = self._serialize_fact(fact_row)

            cursor.execute(
                f"""
                UPDATE context_fact_candidates
                   SET status = 'approved',
                       promoted_fact_id = %s,
                       revision = revision + 1
                 WHERE id = %s AND user_id = %s
                   AND status = 'pending' AND revision = %s
                RETURNING {_CANDIDATE_SELECT_COLUMNS}
                """,
                (fact["id"], candidate_id, user_id, expected_revision),
            )
            approved_row = cursor.fetchone()
            if approved_row is None:
                raise ApiServiceError(
                    ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
                    409,
                    status="fail",
                )
            return self._serialize_candidate(approved_row), fact

        return self._run_write(op, error_message="Failed to approve context fact candidate.")

    def reject_candidate(
        self,
        user_id: int,
        candidate_id: int,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Reject a pending candidate with optimistic locking."""

        def op(cursor: Any) -> dict[str, Any]:
            cursor.execute(
                f"""
                UPDATE context_fact_candidates
                   SET status = 'rejected', revision = revision + 1
                 WHERE id = %s AND user_id = %s
                   AND status = 'pending' AND revision = %s
                RETURNING {_CANDIDATE_SELECT_COLUMNS}
                """,
                (candidate_id, user_id, expected_revision),
            )
            row = cursor.fetchone()
            if row is not None:
                return self._serialize_candidate(row)
            cursor.execute(
                "SELECT 1 FROM context_fact_candidates WHERE id = %s AND user_id = %s",
                (candidate_id, user_id),
            )
            if cursor.fetchone() is None:
                raise ResourceNotFoundError(ERROR_CONTEXT_FACT_CANDIDATE_NOT_FOUND)
            raise ApiServiceError(
                ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
                409,
                status="fail",
            )

        return self._run_write(op, error_message="Failed to reject context fact candidate.")

    def get_extraction_settings(self, user_id: int) -> bool:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT COALESCE(context_auto_extract_enabled, FALSE) "
                    "FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cursor.fetchone()
                return bool(row[0]) if row is not None else False
            finally:
                cursor.close()

    def update_extraction_settings(self, user_id: int, enabled: bool) -> bool:
        def op(cursor: Any) -> bool:
            cursor.execute(
                "UPDATE users SET context_auto_extract_enabled = %s "
                "WHERE id = %s RETURNING context_auto_extract_enabled",
                (bool(enabled), user_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise ResourceNotFoundError(ERROR_CONTEXT_EXTRACTION_SETTINGS_NOT_FOUND)
            return bool(row[0])

        return self._run_write(op, error_message="Failed to update context extraction settings.")

    def should_extract_context(self, user_id: int) -> bool:
        """Return opt-in and queue-capacity state with one database read."""
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT
                        COALESCE(u.context_auto_extract_enabled, FALSE),
                        (
                            SELECT COUNT(*)
                              FROM context_fact_candidates c
                             WHERE c.user_id = u.id AND c.status = 'pending'
                        ) < %s
                      FROM users u
                     WHERE u.id = %s
                    """,
                    (MAX_PENDING_CONTEXT_FACT_CANDIDATES, user_id),
                )
                row = cursor.fetchone()
                return bool(row and row[0] and row[1])
            finally:
                cursor.close()
