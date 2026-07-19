from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.db import Error, get_db_connection, is_retryable_db_error, rollback_connection

DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05

# active な事実の上限。get_personal_context ダイジェストと文脈注入のサイズを有界に保つ。
# Cap on active facts so the personal-context digest and injected context stay bounded.
MAX_ACTIVE_CONTEXT_FACTS = 200

ERROR_CONTEXT_FACT_NOT_FOUND = "該当するコンテキストが見つかりません。"
ERROR_CONTEXT_FACT_REVISION_CONFLICT = (
    "他の場所で先に更新されました。最新の内容を読み込み直してからやり直してください。"
)
ERROR_CONTEXT_FACT_LIMIT_REACHED = (
    f"保存できる有効なコンテキストは{MAX_ACTIVE_CONTEXT_FACTS}件までです。"
    "不要な項目を無効化してから追加してください。"
)

# context_facts の全カラム。返却順を固定してタプル→dict 変換を安全にする。
# All context_facts columns, in a fixed order so tuple→dict mapping stays stable.
_FACT_COLUMNS = (
    "id",
    "user_id",
    "fact_type",
    "title",
    "content",
    "status",
    "revision",
    "created_at",
    "updated_at",
)
_SELECT_COLUMNS = ", ".join(_FACT_COLUMNS)


class ContextFactRepository:
    """context_facts の永続化境界。ProjectRepository と同じくテストで依存を差し替えられる。

    Persistence boundary for context_facts. Like ProjectRepository, its dependencies
    can be injected in tests to exercise retries without a real database.
    """

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

    # ----- write retry helper ------------------------------------------------

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

    # ----- serialization -----------------------------------------------------

    @staticmethod
    def _serialize_row(row: Any) -> dict[str, Any]:
        record = dict(zip(_FACT_COLUMNS, row))
        return {
            "id": int(record["id"]),
            "user_id": int(record["user_id"]),
            "fact_type": str(record["fact_type"]),
            "title": str(record["title"] or ""),
            "content": str(record["content"] or ""),
            "status": str(record["status"] or "active"),
            "revision": max(int(record["revision"] or 1), 1),
            "created_at": serialize_datetime_iso(record["created_at"]),
            "updated_at": serialize_datetime_iso(record["updated_at"]),
            "_updated_at_raw": record["updated_at"],
        }

    # ----- reads -------------------------------------------------------------

    def count_active(self, user_id: int) -> int:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM context_facts WHERE user_id = %s AND status = 'active'",
                    (user_id,),
                )
                row = cursor.fetchone()
                return int(row[0]) if row else 0
            finally:
                cursor.close()

    def list_facts(
        self,
        user_id: int,
        *,
        fact_type: str | None = None,
        status: str = "active",
        limit: int = 50,
        before_updated_at: datetime | None = None,
        before_id: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions = ["user_id = %s", "status = %s"]
        params: list[Any] = [user_id, status]
        if fact_type is not None:
            conditions.append("fact_type = %s")
            params.append(fact_type)
        # Keyset pagination over the (updated_at DESC, id DESC) index.
        if before_updated_at is not None and before_id is not None:
            conditions.append("(updated_at, id) < (%s, %s)")
            params.extend([before_updated_at, before_id])
        params.append(limit)
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                      FROM context_facts
                     WHERE {" AND ".join(conditions)}
                     ORDER BY updated_at DESC, id DESC
                     LIMIT %s
                    """,
                    tuple(params),
                )
                return [self._serialize_row(row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    def list_active_for_digest(self, user_id: int) -> list[dict[str, Any]]:
        """全 active 事実を updated_at 降順で返す。件数上限があるため一括取得で足りる。"""
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                      FROM context_facts
                     WHERE user_id = %s AND status = 'active'
                     ORDER BY updated_at DESC, id DESC
                     LIMIT %s
                    """,
                    (user_id, MAX_ACTIVE_CONTEXT_FACTS),
                )
                return [self._serialize_row(row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    def get_fact(self, user_id: int, fact_id: int) -> dict[str, Any]:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                      FROM context_facts
                     WHERE id = %s AND user_id = %s
                    """,
                    (fact_id, user_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise ResourceNotFoundError(ERROR_CONTEXT_FACT_NOT_FOUND)
                return self._serialize_row(row)
            finally:
                cursor.close()

    def semantic_search(
        self,
        user_id: int,
        embedding: list[float],
        *,
        limit: int = 20,
        status: str = "active",
    ) -> list[dict[str, Any]]:
        vector_literal = "[" + ",".join(format(float(value), ".9g") for value in embedding) + "]"
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                      FROM context_facts
                     WHERE user_id = %s
                       AND status = %s
                       AND embedding_vector IS NOT NULL
                     ORDER BY embedding_vector <=> %s::vector
                     LIMIT %s
                    """,
                    (user_id, status, vector_literal, limit),
                )
                return [self._serialize_row(row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    def text_search(
        self,
        user_id: int,
        query: str,
        *,
        limit: int = 20,
        status: str = "active",
    ) -> list[dict[str, Any]]:
        like_term = f"%{query}%"
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                      FROM context_facts
                     WHERE user_id = %s
                       AND status = %s
                       AND (title ILIKE %s OR content ILIKE %s)
                     ORDER BY updated_at DESC, id DESC
                     LIMIT %s
                    """,
                    (user_id, status, like_term, like_term, limit),
                )
                return [self._serialize_row(row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    # ----- writes ------------------------------------------------------------

    def create_fact(
        self,
        user_id: int,
        *,
        fact_type: str,
        title: str,
        content: str,
    ) -> dict[str, Any]:
        def op(cursor: Any) -> dict[str, Any]:
            cursor.execute(
                "SELECT COUNT(*) FROM context_facts WHERE user_id = %s AND status = 'active'",
                (user_id,),
            )
            active_count = int((cursor.fetchone() or [0])[0])
            if active_count >= MAX_ACTIVE_CONTEXT_FACTS:
                raise ApiServiceError(ERROR_CONTEXT_FACT_LIMIT_REACHED, 409, status="fail")
            cursor.execute(
                f"""
                INSERT INTO context_facts (user_id, fact_type, title, content)
                VALUES (%s, %s, %s, %s)
                RETURNING {_SELECT_COLUMNS}
                """,
                (user_id, fact_type, title, content),
            )
            return self._serialize_row(cursor.fetchone())

        return self._run_write(op, error_message="Failed to create context fact after retry attempts.")

    def update_fact(
        self,
        user_id: int,
        fact_id: int,
        *,
        expected_revision: int,
        title: str | None = None,
        content: str | None = None,
        fact_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        def op(cursor: Any) -> dict[str, Any]:
            # Enforce the active cap when re-activating a deprecated fact.
            if status == "active":
                cursor.execute(
                    """
                    SELECT status FROM context_facts
                     WHERE id = %s AND user_id = %s
                    """,
                    (fact_id, user_id),
                )
                existing = cursor.fetchone()
                if existing is not None and str(existing[0]) != "active":
                    cursor.execute(
                        "SELECT COUNT(*) FROM context_facts WHERE user_id = %s AND status = 'active'",
                        (user_id,),
                    )
                    active_count = int((cursor.fetchone() or [0])[0])
                    if active_count >= MAX_ACTIVE_CONTEXT_FACTS:
                        raise ApiServiceError(ERROR_CONTEXT_FACT_LIMIT_REACHED, 409, status="fail")

            fields: list[str] = []
            params: list[Any] = []
            if title is not None:
                fields.append("title = %s")
                params.append(title)
            if content is not None:
                fields.append("content = %s")
                params.append(content)
            if fact_type is not None:
                fields.append("fact_type = %s")
                params.append(fact_type)
            if status is not None:
                fields.append("status = %s")
                params.append(status)
            fields.append("revision = revision + 1")
            params.extend([fact_id, user_id, expected_revision])
            cursor.execute(
                f"""
                UPDATE context_facts
                   SET {", ".join(fields)}
                 WHERE id = %s AND user_id = %s AND revision = %s
                 RETURNING {_SELECT_COLUMNS}
                """,
                tuple(params),
            )
            row = cursor.fetchone()
            if row is not None:
                return self._serialize_row(row)
            # No row updated: distinguish "not found" from "revision conflict".
            cursor.execute(
                "SELECT 1 FROM context_facts WHERE id = %s AND user_id = %s",
                (fact_id, user_id),
            )
            if cursor.fetchone() is None:
                raise ResourceNotFoundError(ERROR_CONTEXT_FACT_NOT_FOUND)
            raise ApiServiceError(ERROR_CONTEXT_FACT_REVISION_CONFLICT, 409, status="fail")

        return self._run_write(op, error_message="Failed to update context fact after retry attempts.")

    def store_embedding(
        self,
        fact_id: int,
        embedding: list[float],
        expected_revision: int | None = None,
    ) -> None:
        vector_literal = "[" + ",".join(format(float(value), ".9g") for value in embedding) + "]"
        revision_clause = " AND revision = %s" if expected_revision is not None else ""
        params: list[Any] = [vector_literal, fact_id]
        if expected_revision is not None:
            params.append(expected_revision)

        def op(cursor: Any) -> None:
            cursor.execute(
                f"""
                UPDATE context_facts
                   SET embedding_vector = %s::vector
                 WHERE id = %s{revision_clause}
                """,
                tuple(params),
            )

        self._run_write(op, error_message="Failed to store context fact embedding after retry attempts.")
