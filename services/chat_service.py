import secrets
import time
from typing import Any

from .api_errors import ForbiddenOperationError, ResourceNotFoundError
from .db import Error, get_db_connection, is_retryable_db_error, rollback_connection
from .datetime_serialization import serialize_datetime_iso
from .error_messages import ERROR_CHAT_ROOM_NOT_FOUND, ERROR_SHARED_LINK_NOT_FOUND

UNIQUE_VIOLATION_PGCODE = "23505"
DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
SHARED_TOKEN_MAX_COLLISION_RETRIES = 5


def save_message_to_db(chat_room_id: str, message: str, sender: str) -> int | None:
    # チャットメッセージを履歴テーブルへ追加する
    # Insert a chat message into the history table.
    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        with get_db_connection() as conn:
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
                rollback_connection(conn)
                if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                    time.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise
            except BaseException:
                rollback_connection(conn)
                raise
            finally:
                cursor.close()

    raise RuntimeError("Failed to save chat message after retry attempts.")


def create_chat_room_in_db(room_id: str, user_id: int, title: str, mode: str = "normal") -> None:
    # チャットルームのメタ情報を保存する
    # Persist chat room metadata.
    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                query = "INSERT INTO chat_rooms (id, user_id, title, mode) VALUES (%s, %s, %s, %s)"
                cursor.execute(query, (room_id, user_id, title, mode))
                conn.commit()
                return
            except Error as exc:
                rollback_connection(conn)
                if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                    time.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise
            except BaseException:
                rollback_connection(conn)
                raise
            finally:
                cursor.close()

    raise RuntimeError("Failed to create chat room after retry attempts.")


def delete_chat_room_if_no_assistant_messages(room_id: str, user_id: int) -> bool:
    # assistant 発言が一度もないルームだけ履歴ごと削除する
    # Delete the room and its history only when no assistant message exists yet.
    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        with get_db_connection() as conn:
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
                rollback_connection(conn)
                if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                    time.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise
            except BaseException:
                rollback_connection(conn)
                raise
            finally:
                cursor.close()

    raise RuntimeError("Failed to delete chat room without assistant messages after retry attempts.")


def rename_chat_room_in_db(room_id: str, new_title: str) -> None:
    # 既存チャットルームのタイトルを更新する
    # Update the title of an existing chat room.
    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                query = "UPDATE chat_rooms SET title = %s WHERE id = %s"
                cursor.execute(query, (new_title, room_id))
                conn.commit()
                return
            except Error as exc:
                rollback_connection(conn)
                if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                    time.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise
            except BaseException:
                rollback_connection(conn)
                raise
            finally:
                cursor.close()

    raise RuntimeError("Failed to rename chat room after retry attempts.")


def get_chat_room_messages(chat_room_id: str) -> list[dict[str, str]]:
    # LLM へ渡す role/content 形式で履歴を整形して返す
    # Return history formatted as role/content messages for LLM calls.
    """GPTへのAPI呼び出しに使う形で取得"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        messages = []
        try:
            query = (
                "SELECT message, sender FROM chat_history WHERE chat_room_id = %s ORDER BY id ASC"
            )
            cursor.execute(query, (chat_room_id,))
            rows = cursor.fetchall()
            for (message, sender) in rows:
                role = 'user' if sender == 'user' else 'assistant'
                messages.append({"role": role, "content": message})
            return messages
        finally:
            cursor.close()


def validate_room_owner(
    room_id: str, user_id: int, forbidden_message: str
) -> str | None:
    # 指定ルームの所有者チェックを行い、失敗時は例外を送出する
    # Validate room ownership and raise API service errors on failure.
    with get_db_connection() as conn:
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


def create_or_get_shared_chat_token(room_id: str, user_id: int) -> str:
    # 共有リンク用トークンを作成し、既存がある場合は再利用する
    # Create share token for a room and reuse the existing one when present.
    for _ in range(SHARED_TOKEN_MAX_COLLISION_RETRIES):
        token = secrets.token_urlsafe(18)
        collision_detected = False

        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with get_db_connection() as conn:
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
                    # Missing room is a business condition, not a write failure.
                    raise
                except Exception as exc:
                    rollback_connection(conn)
                    if getattr(exc, "pgcode", None) == UNIQUE_VIOLATION_PGCODE:
                        collision_detected = True
                        break
                    if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        time.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                finally:
                    cursor.close()

        if collision_detected:
            continue

    raise RuntimeError("Failed to create shared chat token after collision retries.")


def get_shared_chat_room_payload(
    token: str,
) -> dict[str, Any]:
    # 共有トークンに対応する公開チャット履歴を返す
    # Return publicly viewable chat payload for the given share token.
    with get_db_connection() as conn:
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
