from __future__ import annotations

import os
import secrets
import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request

from .db import Error, get_db_connection, is_retryable_db_error, rollback_connection
from .web import FRONTEND_URL

DEFAULT_PASSKEY_RP_NAME = "Chat Core"
PASSKEY_CHALLENGE_TTL_SECONDS = 300
PASSKEY_REGISTRATION_SESSION_KEY = "passkey_registration"
PASSKEY_AUTHENTICATION_SESSION_KEY = "passkey_authentication"
DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05


# 日本語: get passkey rp name の取得処理を担当します。
# English: Handle fetching for get passkey rp name.
def get_passkey_rp_name() -> str:
    configured_name = (os.getenv("WEBAUTHN_RP_NAME") or os.getenv("PASSKEY_RP_NAME") or "").strip()
    return configured_name or DEFAULT_PASSKEY_RP_NAME


# 日本語: get passkey rp id の取得処理を担当します。
# English: Handle fetching for get passkey rp id.
def get_passkey_rp_id(request: Request) -> str:
    configured_rp_id = (os.getenv("WEBAUTHN_RP_ID") or os.getenv("PASSKEY_RP_ID") or "").strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if configured_rp_id:
        return configured_rp_id

    candidates = (
        FRONTEND_URL,
        str(request.base_url),
        str(request.url),
    )
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for candidate in candidates:
        hostname = urlsplit(candidate).hostname
        if isinstance(hostname, str) and hostname:
            return hostname

    return "localhost"


# 日本語: get passkey origins の取得処理を担当します。
# English: Handle fetching for get passkey origins.
def get_passkey_origins(request: Request) -> list[str]:
    configured_env = (os.getenv("PASSKEY_ORIGINS") or os.getenv("WEBAUTHN_ORIGINS") or "").strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if configured_env:
        explicit = [o.strip() for o in configured_env.split(",") if o.strip()]
        if explicit:
            return explicit

    origins: list[str] = []
    candidates = (
        FRONTEND_URL,
        str(request.base_url),
        str(request.url),
    )
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for candidate in candidates:
        parts = urlsplit(candidate)
        if not parts.scheme or not parts.netloc:
            continue
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in origins:
            origins.append(origin)
    return origins or ["http://localhost:3000"]


# 日本語: clear passkey session の初期化処理を担当します。
# English: Handle clearing for clear passkey session.
def clear_passkey_session(session: dict[str, Any]) -> None:
    session.pop(PASSKEY_REGISTRATION_SESSION_KEY, None)
    session.pop(PASSKEY_AUTHENTICATION_SESSION_KEY, None)


# 日本語: store passkey registration ceremony に関する処理の入口です。
# English: Entry point for logic related to store passkey registration ceremony.
def store_passkey_registration_ceremony(
    session: dict[str, Any], challenge: str
) -> dict[str, Any]:
    return _store_passkey_ceremony(session, PASSKEY_REGISTRATION_SESSION_KEY, challenge)


# 日本語: store passkey authentication ceremony に関する処理の入口です。
# English: Entry point for logic related to store passkey authentication ceremony.
def store_passkey_authentication_ceremony(
    session: dict[str, Any], challenge: str
) -> dict[str, Any]:
    return _store_passkey_ceremony(session, PASSKEY_AUTHENTICATION_SESSION_KEY, challenge)


# 日本語: get passkey registration ceremony の取得処理を担当します。
# English: Handle fetching for get passkey registration ceremony.
def get_passkey_registration_ceremony(session: dict[str, Any]) -> dict[str, Any] | None:
    return _load_passkey_ceremony(session.get(PASSKEY_REGISTRATION_SESSION_KEY))


# 日本語: get passkey authentication ceremony の取得処理を担当します。
# English: Handle fetching for get passkey authentication ceremony.
def get_passkey_authentication_ceremony(session: dict[str, Any]) -> dict[str, Any] | None:
    return _load_passkey_ceremony(session.get(PASSKEY_AUTHENTICATION_SESSION_KEY))


# 日本語: passkey ceremony is expired に関する処理の入口です。
# English: Entry point for logic related to passkey ceremony is expired.
def passkey_ceremony_is_expired(
    ceremony: dict[str, Any], *, now: int | None = None
) -> bool:
    issued_at = int(ceremony.get("issued_at") or 0)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if issued_at <= 0:
        return True

    current_time = int(time.time()) if now is None else int(now)
    return current_time - issued_at > PASSKEY_CHALLENGE_TTL_SECONDS


# 日本語: get credential lookup id の取得処理を担当します。
# English: Handle fetching for get credential lookup id.
def get_credential_lookup_id(credential: dict[str, Any]) -> str | None:
    raw_id = credential.get("rawId")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(raw_id, str) and raw_id:
        return raw_id

    credential_id = credential.get("id")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(credential_id, str) and credential_id:
        return credential_id

    return None


# 日本語: store passkey ceremony に関する処理の入口です。
# English: Entry point for logic related to store passkey ceremony.
def _store_passkey_ceremony(
    session: dict[str, Any], session_key: str, challenge: str
) -> dict[str, Any]:
    clear_passkey_session(session)
    ceremony = {
        "challenge": challenge,
        "issued_at": int(time.time()),
        "ceremony_id": secrets.token_urlsafe(16),
    }
    session[session_key] = ceremony
    return ceremony


# 日本語: load passkey ceremony の読み込み処理を担当します。
# English: Handle loading for load passkey ceremony.
def _load_passkey_ceremony(raw_state: Any) -> dict[str, Any] | None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not isinstance(raw_state, dict):
        return None

    challenge = raw_state.get("challenge")
    ceremony_id = raw_state.get("ceremony_id")
    issued_at = raw_state.get("issued_at")

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not isinstance(challenge, str) or not challenge:
        return None
    if not isinstance(ceremony_id, str) or not ceremony_id:
        return None

    try:
        normalized_issued_at = int(issued_at)
    except (TypeError, ValueError):
        return None

    if normalized_issued_at <= 0:
        return None

    return {
        "challenge": challenge,
        "issued_at": normalized_issued_at,
        "ceremony_id": ceremony_id,
    }


# 日本語: list passkeys for user の一覧取得処理を担当します。
# English: Handle listing for list passkeys for user.
def list_passkeys_for_user(user_id: int) -> list[dict[str, Any]]:
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT id,
                       credential_id,
                       sign_count,
                       aaguid,
                       credential_device_type,
                       credential_backed_up,
                       label,
                       created_at,
                       last_used_at
                  FROM user_passkeys
                 WHERE user_id = %s
                 ORDER BY created_at DESC, id DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall() or []
            return [dict(row) for row in rows]
        finally:
            cursor.close()


# 日本語: get passkey by credential id の取得処理を担当します。
# English: Handle fetching for get passkey by credential id.
def get_passkey_by_credential_id(credential_id: str) -> dict[str, Any] | None:
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT id,
                       user_id,
                       credential_id,
                       public_key,
                       sign_count,
                       aaguid,
                       credential_device_type,
                       credential_backed_up,
                       label,
                       created_at,
                       last_used_at
                  FROM user_passkeys
                 WHERE credential_id = %s
                """,
                (credential_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            cursor.close()


# 日本語: create passkey の作成処理を担当します。
# English: Handle creating for create passkey.
def create_passkey(
    user_id: int,
    credential_id: str,
    public_key: str,
    sign_count: int,
    *,
    aaguid: str | None = None,
    credential_device_type: str | None = None,
    credential_backed_up: bool = False,
    label: str | None = None,
) -> dict[str, Any] | None:
    normalized_label = (label or "").strip() or None
    normalized_aaguid = (aaguid or "").strip() or None
    normalized_device_type = (credential_device_type or "").strip() or None

    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    INSERT INTO user_passkeys (
                        user_id,
                        credential_id,
                        public_key,
                        sign_count,
                        aaguid,
                        credential_device_type,
                        credential_backed_up,
                        label,
                        last_used_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id,
                              credential_id,
                              sign_count,
                              aaguid,
                              credential_device_type,
                              credential_backed_up,
                              label,
                              created_at,
                              last_used_at
                    """,
                    (
                        user_id,
                        credential_id,
                        public_key,
                        int(sign_count),
                        normalized_aaguid,
                        normalized_device_type,
                        bool(credential_backed_up),
                        normalized_label,
                    ),
                )
                conn.commit()
                row = cursor.fetchone()
                return dict(row) if row else None
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

    raise RuntimeError("Failed to create passkey after retry attempts.")


# 日本語: update passkey usage の更新処理を担当します。
# English: Handle updating for update passkey usage.
def update_passkey_usage(
    passkey_id: int,
    sign_count: int,
    *,
    credential_backed_up: bool | None = None,
    credential_device_type: str | None = None,
) -> None:
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE user_passkeys
                       SET sign_count = %s,
                           credential_backed_up = COALESCE(%s, credential_backed_up),
                           credential_device_type = COALESCE(%s, credential_device_type),
                           last_used_at = CURRENT_TIMESTAMP
                     WHERE id = %s
                    """,
                    (
                        int(sign_count),
                        credential_backed_up,
                        (credential_device_type or "").strip() or None,
                        passkey_id,
                    ),
                )
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

    raise RuntimeError("Failed to update passkey usage after retry attempts.")


# 日本語: delete passkey の削除処理を担当します。
# English: Handle deleting for delete passkey.
def delete_passkey(user_id: int, passkey_id: int) -> bool:
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    DELETE FROM user_passkeys
                     WHERE id = %s
                       AND user_id = %s
                    """,
                    (passkey_id, user_id),
                )
                deleted = cursor.rowcount > 0
                conn.commit()
                return deleted
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

    raise RuntimeError("Failed to delete passkey after retry attempts.")
