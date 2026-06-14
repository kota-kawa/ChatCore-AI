from __future__ import annotations

from datetime import datetime, timedelta
import secrets
import time
from typing import Any

from .api_errors import ResourceNotFoundError
from .db import Error, get_db_connection, is_retryable_db_error, rollback_connection
from .datetime_serialization import serialize_datetime_iso
from .error_messages import ERROR_MEMO_NOT_FOUND_FOR_SHARE, ERROR_SHARED_LINK_NOT_FOUND

UNIQUE_VIOLATION_PGCODE = "23505"
DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
SHARED_TOKEN_MAX_COLLISION_RETRIES = 5
DEFAULT_SHARE_EXPIRES_DAYS = 30


# 日本語: 指定された期限日時が現時刻を過ぎている（有効期限切れ）か判定します。
# English: Check whether the given expiration datetime has passed.
def _is_expired(expires_at: Any) -> bool:
    if not isinstance(expires_at, datetime):
        return False
    return expires_at <= datetime.utcnow()


# 日本語: 共有トークンの有効状態や期限切れステータスをシリアライズして辞書で返します。
# English: Serialize the shared token active/expired/revoked state into a dictionary.
def _serialize_share_state(
    share_token: str | None,
    expires_at: datetime | None,
    revoked_at: datetime | None,
    *,
    is_reused: bool = False,
) -> dict[str, Any]:
    is_active = bool(share_token) and revoked_at is None and not _is_expired(expires_at)
    return {
        "share_token": share_token or "",
        "expires_at": serialize_datetime_iso(expires_at),
        "revoked_at": serialize_datetime_iso(revoked_at),
        "is_expired": _is_expired(expires_at),
        "is_revoked": revoked_at is not None,
        "is_active": is_active,
        "is_reused": is_reused,
    }


# 日本語: 指定日数後の期限切れ日時(datetime)を算出します。
# English: Calculate the future expiration datetime based on the number of days.
def _resolve_expires_at(expires_in_days: int | None) -> datetime | None:
    if expires_in_days is None:
        return None
    return datetime.utcnow() + timedelta(days=max(int(expires_in_days), 1))


# 日本語: メモの共有トークンを作成または既存の有効なトークンを取得して返します。衝突発生時は再試行します。
# English: Create a share token for a memo or retrieve an active existing one. Retries on database collisions.
def create_or_get_shared_memo_token(
    memo_id: int,
    user_id: int,
    *,
    force_refresh: bool = False,
    expires_in_days: int | None = DEFAULT_SHARE_EXPIRES_DAYS,
) -> dict[str, Any]:
    # メモ所有者を検証した上で共有トークンを作成し、既存があれば再利用する
    # Create a memo share token after owner validation and reuse the existing one.
    for _ in range(SHARED_TOKEN_MAX_COLLISION_RETRIES):
        token = secrets.token_urlsafe(18)
        collision_detected = False
        expires_at = _resolve_expires_at(expires_in_days)

        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with get_db_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                try:
                    cursor.execute(
                        "SELECT 1 FROM memo_entries WHERE id = %s AND user_id = %s",
                        (memo_id, user_id),
                    )
                    if not cursor.fetchone():
                        raise ResourceNotFoundError(ERROR_MEMO_NOT_FOUND_FOR_SHARE)

                    if not force_refresh:
                        cursor.execute(
                            """
                            SELECT share_token, expires_at, revoked_at
                            FROM shared_memo_entries
                            WHERE memo_entry_id = %s
                            LIMIT 1
                            """,
                            (memo_id,),
                        )
                        existing = cursor.fetchone()
                        if existing:
                            serialized_existing = _serialize_share_state(
                                existing.get("share_token"),
                                existing.get("expires_at"),
                                existing.get("revoked_at"),
                                is_reused=True,
                            )
                            if serialized_existing["is_active"]:
                                return serialized_existing

                    cursor.execute(
                        """
                        INSERT INTO shared_memo_entries (memo_entry_id, share_token, expires_at, revoked_at, created_at)
                        VALUES (%s, %s, %s, NULL, CURRENT_TIMESTAMP)
                        ON CONFLICT (memo_entry_id)
                        DO UPDATE
                        SET
                            share_token = EXCLUDED.share_token,
                            expires_at = EXCLUDED.expires_at,
                            revoked_at = NULL,
                            created_at = CURRENT_TIMESTAMP
                        RETURNING share_token, expires_at, revoked_at
                        """,
                        (memo_id, token, expires_at),
                    )
                    row = cursor.fetchone()
                    conn.commit()
                    if row:
                        return _serialize_share_state(
                            row.get("share_token"),
                            row.get("expires_at"),
                            row.get("revoked_at"),
                            is_reused=False,
                        )
                    return _serialize_share_state(token, expires_at, None, is_reused=False)
                except ResourceNotFoundError:
                    raise
                except Error as exc:
                    rollback_connection(conn)
                    if getattr(exc, "pgcode", None) == UNIQUE_VIOLATION_PGCODE:
                        collision_detected = True
                        break
                    if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        time.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    rollback_connection(conn)
                    raise
                finally:
                    cursor.close()

        if collision_detected:
            continue

    raise RuntimeError("Failed to create shared memo token after collision retries.")


# 日本語: メモの共有状態（有効期限、無効化状況）を取得してシリアライズして返します。
# English: Retrieve and serialize the current share status of the specified memo.
def get_memo_share_state(memo_id: int, user_id: int) -> dict[str, Any]:
    # 日本語: コンテキストマネージャを使用して、必要なリソースの確保とクリーンアップを制御します。
    # English: Secure and clean up the required resource using a context manager.
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT 1 FROM memo_entries WHERE id = %s AND user_id = %s",
                (memo_id, user_id),
            )
            if not cursor.fetchone():
                raise ResourceNotFoundError(ERROR_MEMO_NOT_FOUND_FOR_SHARE)

            cursor.execute(
                """
                SELECT share_token, expires_at, revoked_at
                FROM shared_memo_entries
                WHERE memo_entry_id = %s
                LIMIT 1
                """,
                (memo_id,),
            )
            row = cursor.fetchone()
            if not row:
                return _serialize_share_state(None, None, None)
            return _serialize_share_state(
                row.get("share_token"),
                row.get("expires_at"),
                row.get("revoked_at"),
            )
        finally:
            cursor.close()


# 日本語: メモの共有トークンを無効化（削除に近い更新）処理します。
# English: Revoke/invalidate the active share token for the memo in the database.
def revoke_shared_memo_token(memo_id: int, user_id: int) -> dict[str, Any]:
    # 日本語: コンテキストマネージャを使用して、必要なリソースの確保とクリーンアップを制御します。
    # English: Secure and clean up the required resource using a context manager.
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT 1 FROM memo_entries WHERE id = %s AND user_id = %s",
                (memo_id, user_id),
            )
            if not cursor.fetchone():
                raise ResourceNotFoundError(ERROR_MEMO_NOT_FOUND_FOR_SHARE)

            cursor.execute(
                """
                UPDATE shared_memo_entries
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE memo_entry_id = %s
                RETURNING share_token, expires_at, revoked_at
                """,
                (memo_id,),
            )
            row = cursor.fetchone()
            conn.commit()
            if not row:
                return _serialize_share_state(None, None, None)
            return _serialize_share_state(
                row.get("share_token"),
                row.get("expires_at"),
                row.get("revoked_at"),
            )
        finally:
            cursor.close()


# 日本語: 共有トークンに紐づく、一般公開されているメモの内容を取得して返します。
# English: Retrieve the publicly shared memo content by its unique share token.
def get_shared_memo_payload(token: str) -> dict[str, Any]:
    # 共有トークンに対応する公開メモ内容を返す
    # Return publicly viewable memo payload for the given share token.
    # 日本語: コンテキストマネージャを使用して、必要なリソースの確保とクリーンアップを制御します。
    # English: Secure and clean up the required resource using a context manager.
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    me.id,
                    me.title,
                    me.created_at,
                    me.ai_response,
                    me.background_color
                FROM shared_memo_entries sme
                JOIN memo_entries me ON me.id = sme.memo_entry_id
                WHERE sme.share_token = %s
                  AND sme.revoked_at IS NULL
                  AND (sme.expires_at IS NULL OR sme.expires_at > CURRENT_TIMESTAMP)
                LIMIT 1
                """,
                (token,),
            )
            row = cursor.fetchone()
            if not row:
                raise ResourceNotFoundError(ERROR_SHARED_LINK_NOT_FOUND)

            created_at = row.get("created_at")
            return {
                "memo": {
                    "id": row.get("id"),
                    "title": row.get("title") or "保存したメモ",
                    "created_at": serialize_datetime_iso(created_at),
                    "ai_response": row.get("ai_response") or "",
                    "background_color": row.get("background_color"),
                }
            }
        finally:
            cursor.close()
