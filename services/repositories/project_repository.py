from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.db import Error, get_db_connection, is_retryable_db_error, rollback_connection

DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05

ERROR_PROJECT_NOT_FOUND = "該当プロジェクトが見つかりません"
ERROR_PROJECT_FORBIDDEN = "他ユーザーのプロジェクトは操作できません"
# プロジェクト名・指示の上限。極端に大きな入力で DB / 文脈を圧迫しないよう制限する。
# Limits for project name / instructions to avoid bloating the DB and LLM context.
MAX_PROJECT_NAME_LENGTH = 255
MAX_PROJECT_INSTRUCTIONS_LENGTH = 20_000


class ProjectRepository:
    # projects / chat_rooms.project_id の永続化をまとめる境界。
    # ChatRepository と同じく、テストで connection_getter / sleep を差し替えられる。
    #
    # Boundary class coordinating persistence for projects and the chat_rooms.project_id
    # association. Like ChatRepository, connection_getter / sleep can be injected in
    # tests to exercise retries without a real database.

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
        # 書き込み系の定型処理（再試行・ロールバック・コミット）をまとめる。
        # operation(cursor) は値を返してよく、コミット後にその値を返す。
        # Shared write boilerplate (retry, rollback, commit). operation(cursor) may
        # return a value which is returned after commit.
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    result = operation(cursor)
                    conn.commit()
                    return result
                except (ResourceNotFoundError, ForbiddenOperationError):
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
    def _normalize_name(name: Any) -> str:
        normalized = str(name or "").strip() or "新規プロジェクト"
        return normalized[:MAX_PROJECT_NAME_LENGTH]

    @staticmethod
    def _normalize_instructions(instructions: Any) -> str | None:
        if instructions is None:
            return None
        text = str(instructions)
        return text[:MAX_PROJECT_INSTRUCTIONS_LENGTH]

    # ----- ownership ---------------------------------------------------------

    def _require_owned_project(self, cursor: Any, project_id: int, user_id: int) -> None:
        cursor.execute("SELECT user_id FROM projects WHERE id = %s", (project_id,))
        row = cursor.fetchone()
        if not row:
            raise ResourceNotFoundError(ERROR_PROJECT_NOT_FOUND)
        if row[0] != user_id:
            raise ForbiddenOperationError(ERROR_PROJECT_FORBIDDEN)

    # ----- project CRUD ------------------------------------------------------

    def create_project(self, user_id: int, name: str, instructions: str | None = None) -> dict[str, Any]:
        normalized_name = self._normalize_name(name)
        normalized_instructions = self._normalize_instructions(instructions)

        def op(cursor: Any) -> dict[str, Any]:
            cursor.execute(
                """
                INSERT INTO projects (user_id, name, instructions)
                VALUES (%s, %s, %s)
                RETURNING id, name, instructions, created_at, updated_at
                """,
                (user_id, normalized_name, normalized_instructions),
            )
            row = cursor.fetchone()
            return self._serialize_project_row(row)

        return self._run_write(op, error_message="Failed to create project after retry attempts.")

    def list_projects(self, user_id: int) -> list[dict[str, Any]]:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT p.id, p.name, p.instructions, p.created_at, p.updated_at,
                           COUNT(DISTINCT cr.id) AS chat_count
                      FROM projects p
                      LEFT JOIN chat_rooms cr ON cr.project_id = p.id
                     WHERE p.user_id = %s
                     GROUP BY p.id
                     ORDER BY p.created_at DESC, p.id DESC
                    """,
                    (user_id,),
                )
                rows = cursor.fetchall()
                return [self._serialize_project_row(row, with_counts=True) for row in rows]
            finally:
                cursor.close()

    def get_project(self, project_id: int, user_id: int) -> dict[str, Any]:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT id, name, instructions, created_at, updated_at, user_id
                      FROM projects
                     WHERE id = %s
                    """,
                    (project_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise ResourceNotFoundError(ERROR_PROJECT_NOT_FOUND)
                if row[5] != user_id:
                    raise ForbiddenOperationError(ERROR_PROJECT_FORBIDDEN)
                project = self._serialize_project_row(row)
                project["rooms"] = self._list_rooms(cursor, project_id)
                return project
            finally:
                cursor.close()

    def update_project(
        self,
        project_id: int,
        user_id: int,
        *,
        name: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        def op(cursor: Any) -> dict[str, Any]:
            self._require_owned_project(cursor, project_id, user_id)
            fields: list[str] = []
            params: list[Any] = []
            if name is not None:
                fields.append("name = %s")
                params.append(self._normalize_name(name))
            if instructions is not None:
                fields.append("instructions = %s")
                params.append(self._normalize_instructions(instructions))
            fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(project_id)
            cursor.execute(
                f"""
                UPDATE projects SET {", ".join(fields)}
                 WHERE id = %s
                 RETURNING id, name, instructions, created_at, updated_at
                """,
                tuple(params),
            )
            return self._serialize_project_row(cursor.fetchone())

        return self._run_write(op, error_message="Failed to update project after retry attempts.")

    def delete_project(self, project_id: int, user_id: int) -> None:
        def op(cursor: Any) -> None:
            self._require_owned_project(cursor, project_id, user_id)
            # chat_rooms.project_id は ON DELETE SET NULL のため、配下チャットは残る。
            # chat_rooms.project_id uses ON DELETE SET NULL, so the chats survive.
            cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))

        self._run_write(op, error_message="Failed to delete project after retry attempts.")

    # ----- room association --------------------------------------------------

    def assign_room_to_project(self, room_id: str, user_id: int, project_id: int | None) -> None:
        def op(cursor: Any) -> None:
            cursor.execute("SELECT user_id FROM chat_rooms WHERE id = %s", (room_id,))
            room = cursor.fetchone()
            if not room:
                raise ResourceNotFoundError("該当ルームが見つかりません")
            if room[0] != user_id:
                raise ForbiddenOperationError("他ユーザーのチャットルームは操作できません")
            if project_id is not None:
                self._require_owned_project(cursor, project_id, user_id)
            cursor.execute(
                "UPDATE chat_rooms SET project_id = %s WHERE id = %s",
                (project_id, room_id),
            )

        self._run_write(op, error_message="Failed to assign room to project after retry attempts.")

    def list_project_rooms(self, project_id: int, user_id: int) -> list[dict[str, Any]]:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                self._require_owned_project(cursor, project_id, user_id)
                return self._list_rooms(cursor, project_id)
            finally:
                cursor.close()

    # ----- context injection -------------------------------------------------

    def get_project_context(self, room_id: str) -> dict[str, Any] | None:
        # チャットルームが所属するプロジェクトの指示を取得する。
        # 未所属なら None。LLM 文脈注入に使う。
        # Return the instructions for the room's project.
        # None when the room belongs to no project. Used for LLM context injection.
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT p.id, p.name, p.instructions
                      FROM chat_rooms cr
                      JOIN projects p ON p.id = cr.project_id
                     WHERE cr.id = %s
                    """,
                    (room_id,),
                )
                project = cursor.fetchone()
                if not project:
                    return None
                return {
                    "project_id": project[0],
                    "name": str(project[1] or ""),
                    "instructions": str(project[2] or "").strip(),
                }
            finally:
                cursor.close()

    # ----- serialization helpers --------------------------------------------

    def _list_rooms(self, cursor: Any, project_id: int) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT id, title, COALESCE(mode, 'normal'), created_at
              FROM chat_rooms
             WHERE project_id = %s
             ORDER BY created_at DESC, id DESC
            """,
            (project_id,),
        )
        rooms: list[dict[str, Any]] = []
        for (room_id, title, mode, created_at) in cursor.fetchall():
            rooms.append(
                {
                    "id": room_id,
                    "title": title or "新規チャット",
                    "mode": mode or "normal",
                    "createdAt": serialize_datetime_iso(created_at),
                }
            )
        return rooms

    @staticmethod
    def _serialize_project_row(row: Any, *, with_counts: bool = False) -> dict[str, Any]:
        project = {
            "id": row[0],
            "name": str(row[1] or "新規プロジェクト"),
            "instructions": str(row[2] or ""),
            "createdAt": serialize_datetime_iso(row[3]),
            "updatedAt": serialize_datetime_iso(row[4]),
        }
        if with_counts:
            project["chatCount"] = int(row[5] or 0)
        return project
