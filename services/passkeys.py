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


# 日本語: パスキー(WebAuthn)のRP(Relying Party)名を取得します。
# English: Get the Relying Party name for passkey authentication.
def get_passkey_rp_name() -> str:
    configured_name = (os.getenv("WEBAUTHN_RP_NAME") or os.getenv("PASSKEY_RP_NAME") or "").strip()
    return configured_name or DEFAULT_PASSKEY_RP_NAME


# 日本語: パスキー(WebAuthn)のRP ID（ドメイン）を取得します。
# English: Get the Relying Party ID (domain) for passkey authentication.
def get_passkey_rp_id(request: Request) -> str:
    configured_rp_id = (os.getenv("WEBAUTHN_RP_ID") or os.getenv("PASSKEY_RP_ID") or "").strip()
    if configured_rp_id:
        return configured_rp_id

    candidates = (
        FRONTEND_URL,
        str(request.base_url),
        str(request.url),
    )
    for candidate in candidates:
        hostname = urlsplit(candidate).hostname
        if isinstance(hostname, str) and hostname:
            return hostname

    return "localhost"


# 日本語: WebAuthnで許容されるOrigin(オリジン)の一覧を環境変数またはリクエストから推測して返します。
# English: Get the list of allowed origins for WebAuthn requests.
def get_passkey_origins(request: Request) -> list[str]:
    configured_env = (os.getenv("PASSKEY_ORIGINS") or os.getenv("WEBAUTHN_ORIGINS") or "").strip()
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
    for candidate in candidates:
        parts = urlsplit(candidate)
        if not parts.scheme or not parts.netloc:
            continue
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in origins:
            origins.append(origin)
    return origins or ["http://localhost:3000"]


# 日本語: セッションからパスキー登録・認証途中のチャレンジデータなどをクリアします。
# English: Clear passkey registration and authentication ceremony states from the session.
def clear_passkey_session(session: dict[str, Any]) -> None:
    session.pop(PASSKEY_REGISTRATION_SESSION_KEY, None)
    session.pop(PASSKEY_AUTHENTICATION_SESSION_KEY, None)


# 日本語: 新規パスキー登録用のチャレンジ（Ceremony）をセッションに格納します。
# English: Store the passkey registration challenge state in the session.
def store_passkey_registration_ceremony(
    session: dict[str, Any], challenge: str
) -> dict[str, Any]:
    return _store_passkey_ceremony(session, PASSKEY_REGISTRATION_SESSION_KEY, challenge)


# 日本語: パスキーログイン用のチャレンジ（Ceremony）をセッションに格納します。
# English: Store the passkey authentication challenge state in the session.
def store_passkey_authentication_ceremony(
    session: dict[str, Any], challenge: str
) -> dict[str, Any]:
    return _store_passkey_ceremony(session, PASSKEY_AUTHENTICATION_SESSION_KEY, challenge)


# 日本語: セッションからパスキー登録用のチャレンジ情報を取得します。
# English: Retrieve the passkey registration ceremony from the session.
def get_passkey_registration_ceremony(session: dict[str, Any]) -> dict[str, Any] | None:
    return _load_passkey_ceremony(session.get(PASSKEY_REGISTRATION_SESSION_KEY))


# 日本語: セッションからパスキーログイン用のチャレンジ情報を取得します。
# English: Retrieve the passkey authentication ceremony from the session.
def get_passkey_authentication_ceremony(session: dict[str, Any]) -> dict[str, Any] | None:
    return _load_passkey_ceremony(session.get(PASSKEY_AUTHENTICATION_SESSION_KEY))


# 日本語: チャレンジの発行から一定時間(TTL)が経過し、期限切れになっているかを検証します。
# English: Check whether the passkey challenge ceremony session has expired.
def passkey_ceremony_is_expired(
    ceremony: dict[str, Any], *, now: int | None = None
) -> bool:
    issued_at = int(ceremony.get("issued_at") or 0)
    if issued_at <= 0:
        return True

    current_time = int(time.time()) if now is None else int(now)
    return current_time - issued_at > PASSKEY_CHALLENGE_TTL_SECONDS


# 日本語: クレデンシャルオブジェクトから、データベース照合用のID文字列を抽出します。
# English: Extract the raw credential ID for lookup from the client assertion.
def get_credential_lookup_id(credential: dict[str, Any]) -> str | None:
    raw_id = credential.get("rawId")
    if isinstance(raw_id, str) and raw_id:
        return raw_id

    credential_id = credential.get("id")
    if isinstance(credential_id, str) and credential_id:
        return credential_id

    return None


# 日本語: 新しいWebAuthnチャレンジオブジェクトをセッションに格納します。
# English: Store a new WebAuthn challenge metadata in the session.
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


# 日本語: セッションデータから、チャレンジ情報オブジェクトを検証した上で取得します。
# English: Validate and load the ceremony dict from raw session payload.
def _load_passkey_ceremony(raw_state: Any) -> dict[str, Any] | None:
    if not isinstance(raw_state, dict):
        return None

    challenge = raw_state.get("challenge")
    ceremony_id = raw_state.get("ceremony_id")
    issued_at = raw_state.get("issued_at")

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


# 日本語: ユーザーが登録しているすべてのパスキー一覧を取得します。
# English: Retrieve all registered passkeys for the specified user.
def list_passkeys_for_user(user_id: int) -> list[dict[str, Any]]:
    # 日本語: コンテキストマネージャを使用して、必要なリソースの確保とクリーンアップを制御します。
    # English: Secure and clean up the required resource using a context manager.
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


# 日本語: 指定されたクレデンシャルIDに合致するパスキー情報をデータベースから取得します。
# English: Fetch passkey credential record from the database by credential ID.
def get_passkey_by_credential_id(credential_id: str) -> dict[str, Any] | None:
    # 日本語: コンテキストマネージャを使用して、必要なリソースの確保とクリーンアップを制御します。
    # English: Secure and clean up the required resource using a context manager.
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


# 日本語: 新しく登録されたパスキー情報をデータベースに登録（永続化）します。
# English: Insert a new passkey credential record into the database.
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


# 日本語: パスキーログイン成功時に、署名カウント(sign_count)や最終使用時刻を更新します。
# English: Update the sign counter and last used timestamp for the passkey.
def update_passkey_usage(
    passkey_id: int,
    sign_count: int,
    *,
    credential_backed_up: bool | None = None,
    credential_device_type: str | None = None,
) -> None:
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


# 日本語: 指定されたパスキーをデータベースから削除します。
# English: Delete the specified passkey credential from the database.
def delete_passkey(user_id: int, passkey_id: int) -> bool:
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
