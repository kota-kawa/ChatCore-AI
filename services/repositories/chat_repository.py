from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from typing import Any

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.db import Error, get_db_connection, is_retryable_db_error, rollback_connection
from services.error_messages import ERROR_CHAT_ROOM_NOT_FOUND, ERROR_SHARED_LINK_NOT_FOUND

UNIQUE_VIOLATION_PGCODE = "23505"
DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
SHARED_TOKEN_MAX_COLLISION_RETRIES = 5


class ChatRepository:
    def __init__(
        self,
        *,
        connection_getter: Callable[[], Any] = get_db_connection,
        retryable_error_checker: Callable[[BaseException], bool] = is_retryable_db_error,
        rollback: Callable[[Any], bool] = rollback_connection,
        sleep: Callable[[float], Any] = time.sleep,
        token_generator: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        self._connection_getter = connection_getter
        self._is_retryable_db_error = retryable_error_checker
        self._rollback = rollback
        self._sleep = sleep
        self._token_generator = token_generator

    def save_message(self, chat_room_id: str, message: str, sender: str) -> int | None:
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    query = """
                        INSERT INTO chat_history (chat_room_id, message, sender)
                        VALUES (%s, %s, %s)
                        RETURNING id
                    """
                    cursor.execute(query, (chat_room_id, message, sender))
                    row = cursor.fetchone()
                    conn.commit()
                    return row[0] if row else None
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

        raise RuntimeError("Failed to save chat message after retry attempts.")

    def create_room(self, room_id: str, user_id: int, title: str, mode: str = "normal") -> None:
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    query = "INSERT INTO chat_rooms (id, user_id, title, mode) VALUES (%s, %s, %s, %s)"
                    cursor.execute(query, (room_id, user_id, title, mode))
                    conn.commit()
                    return
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

        raise RuntimeError("Failed to create chat room after retry attempts.")

    def delete_room_if_no_assistant_messages(self, room_id: str, user_id: int) -> bool:
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "SELECT user_id FROM chat_rooms WHERE id = %s",
                        (room_id,),
                    )
                    row = cursor.fetchone()
                    if not row or row[0] != user_id:
                        return False

                    cursor.execute(
                        """
                        SELECT 1
                          FROM chat_history
                         WHERE chat_room_id = %s
                           AND sender = 'assistant'
                         LIMIT 1
                        """,
                        (room_id,),
                    )
                    if cursor.fetchone():
                        return False

                    cursor.execute("DELETE FROM chat_history WHERE chat_room_id = %s", (room_id,))
                    cursor.execute(
                        "DELETE FROM chat_rooms WHERE id = %s AND user_id = %s",
                        (room_id, user_id),
                    )
                    conn.commit()
                    return cursor.rowcount > 0
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

        raise RuntimeError("Failed to delete chat room without assistant messages after retry attempts.")

    def rename_room(self, room_id: str, new_title: str) -> None:
        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with self._connection_getter() as conn:
                cursor = conn.cursor()
                try:
                    query = "UPDATE chat_rooms SET title = %s WHERE id = %s"
                    cursor.execute(query, (new_title, room_id))
                    conn.commit()
                    return
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

        raise RuntimeError("Failed to rename chat room after retry attempts.")

    def get_room_messages_for_llm(self, chat_room_id: str) -> list[dict[str, str]]:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            messages = []
            try:
                query = (
                    "SELECT message, sender FROM chat_history WHERE chat_room_id = %s ORDER BY id ASC"
                )
                cursor.execute(query, (chat_room_id,))
                rows = cursor.fetchall()
                for (message, sender) in rows:
                    role = "user" if sender == "user" else "assistant"
                    messages.append({"role": role, "content": message})
                return messages
            finally:
                cursor.close()

    def validate_room_owner(
        self,
        room_id: str,
        user_id: int,
        forbidden_message: str,
    ) -> str | None:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                check_q = "SELECT user_id, COALESCE(mode, 'normal') FROM chat_rooms WHERE id = %s"
                cursor.execute(check_q, (room_id,))
                result = cursor.fetchone()
                if not result:
                    raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
                if result[0] != user_id:
                    raise ForbiddenOperationError(forbidden_message)
                if len(result) < 2:
                    return None
                return str(result[1] or "normal")
            finally:
                cursor.close()

    def create_or_get_shared_chat_token(self, room_id: str, user_id: int) -> str:
        for _ in range(SHARED_TOKEN_MAX_COLLISION_RETRIES):
            token = self._token_generator(18)
            collision_detected = False

            for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
                with self._connection_getter() as conn:
                    cursor = conn.cursor()
                    try:
                        cursor.execute(
                            "SELECT user_id FROM chat_rooms WHERE id = %s",
                            (room_id,),
                        )
                        room_owner = cursor.fetchone()
                        if not room_owner:
                            raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
                        if room_owner[0] != user_id:
                            raise ForbiddenOperationError("他ユーザーのチャットルームは共有できません")

                        cursor.execute(
                            """
                            INSERT INTO shared_chat_rooms (chat_room_id, share_token)
                            VALUES (%s, %s)
                            ON CONFLICT (chat_room_id)
                            DO UPDATE SET chat_room_id = EXCLUDED.chat_room_id
                            RETURNING share_token
                            """,
                            (room_id, token),
                        )
                        row = cursor.fetchone()
                        conn.commit()
                        return row[0] if row else token
                    except (ResourceNotFoundError, ForbiddenOperationError):
                        raise
                    except Exception as exc:
                        self._rollback(conn)
                        if getattr(exc, "pgcode", None) == UNIQUE_VIOLATION_PGCODE:
                            collision_detected = True
                            break
                        if self._is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                            self._sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                            continue
                        raise
                    finally:
                        cursor.close()

            if collision_detected:
                continue

        raise RuntimeError("Failed to create shared chat token after collision retries.")

    def get_shared_chat_room_payload(self, token: str) -> dict[str, Any]:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT cr.id, cr.title, cr.created_at
                      FROM shared_chat_rooms scr
                      JOIN chat_rooms cr ON cr.id = scr.chat_room_id
                     WHERE scr.share_token = %s
                     LIMIT 1
                    """,
                    (token,),
                )
                room_row = cursor.fetchone()
                if not room_row:
                    raise ResourceNotFoundError(ERROR_SHARED_LINK_NOT_FOUND)

                room_id, title, created_at = room_row
                cursor.execute(
                    """
                    SELECT message, sender, timestamp
                      FROM chat_history
                     WHERE chat_room_id = %s
                     ORDER BY id ASC
                    """,
                    (room_id,),
                )
                rows = cursor.fetchall()
                messages = []
                for (message, sender, timestamp) in rows:
                    messages.append(
                        {
                            "message": message,
                            "sender": sender,
                            "timestamp": serialize_datetime_iso(timestamp),
                        }
                    )

                return {
                    "room": {
                        "id": room_id,
                        "title": title,
                        "created_at": serialize_datetime_iso(created_at),
                    },
                    "messages": messages,
                }
            finally:
                cursor.close()

    def get_task_prompt_data(self, task: str, user_id: int | None) -> dict[str, Any] | None:
        with self._connection_getter() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                if user_id:
                    query = """
                        SELECT name,
                               prompt_template,
                               response_rules,
                               output_skeleton,
                               input_examples,
                               output_examples
                         FROM task_with_examples
                         WHERE name = %s
                           AND deleted_at IS NULL
                           AND (user_id = %s OR user_id IS NULL)
                         ORDER BY CASE WHEN user_id = %s THEN 0 ELSE 1 END, id
                         LIMIT 1
                    """
                    cursor.execute(query, (task, user_id, user_id))
                else:
                    query = """
                        SELECT name,
                               prompt_template,
                               response_rules,
                               output_skeleton,
                               input_examples,
                               output_examples
                         FROM task_with_examples
                         WHERE name = %s
                           AND deleted_at IS NULL
                           AND user_id IS NULL
                         ORDER BY id
                         LIMIT 1
                    """
                    cursor.execute(query, (task,))
                return cursor.fetchone()
            finally:
                cursor.close()

    def fetch_chat_history_page(
        self,
        chat_room_id: str,
        limit: int,
        before_message_id: int | None = None,
    ) -> dict[str, Any]:
        with self._connection_getter() as conn:
            cursor = conn.cursor()
            try:
                query = """
                    SELECT id, message, sender, timestamp
                    FROM (
                        SELECT id, message, sender, timestamp
                        FROM chat_history
                        WHERE chat_room_id = %s
                          AND (%s IS NULL OR id < %s)
                        ORDER BY id DESC
                        LIMIT %s
                    ) recent_history
                    ORDER BY id ASC
                """
                cursor.execute(query, (chat_room_id, before_message_id, before_message_id, limit + 1))
                rows = cursor.fetchall()
                has_more = len(rows) > limit
                if has_more:
                    rows = rows[1:]

                messages = []
                for (message_id, msg, sender, ts) in rows:
                    messages.append(
                        {
                            "id": message_id,
                            "message": msg,
                            "sender": sender,
                            "timestamp": serialize_datetime_iso(ts),
                        }
                    )

                next_before_id = messages[0]["id"] if has_more and messages else None
                return {
                    "messages": messages,
                    "pagination": {
                        "limit": limit,
                        "has_more": has_more,
                        "next_before_id": next_before_id,
                    },
                }
            finally:
                cursor.close()
