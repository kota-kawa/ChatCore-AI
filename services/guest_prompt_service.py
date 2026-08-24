"""Persistence and ownership transfer for unauthenticated shared prompts."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import Any

from services.db import get_db_connection
from services.error_messages import ERROR_GUEST_PROMPT_LIMIT_REACHED
from services.request_models import SharedPromptCreateRequest
from services.runtime_config import get_session_secret_key

logger = logging.getLogger(__name__)

GUEST_PROMPT_SESSION_KEY = "guest_prompt_token"
GUEST_PROMPT_TOKEN_BYTES = 32
GUEST_PROMPT_POST_WINDOW_SECONDS = 24 * 60 * 60
_GUEST_PROMPT_HASH_FALLBACK_SECRET = "chatcore-guest-prompt-hash-v1"
_fallback_secret_warning_logged = False


class GuestPromptLimitExceeded(ValueError):
    """Raised when the cookie or IP already posted within the rolling window."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(int(retry_after), 1)
        super().__init__(
            f"{ERROR_GUEST_PROMPT_LIMIT_REACHED}"
            f"{self.retry_after}秒ほど待ってから再試行してください。"
        )


def get_or_create_guest_prompt_token(session: dict[str, Any]) -> str:
    """Keep a random guest identity in the server-side session behind its cookie."""
    existing = session.get(GUEST_PROMPT_SESSION_KEY)
    if isinstance(existing, str) and len(existing) >= 32:
        return existing

    token = secrets.token_urlsafe(GUEST_PROMPT_TOKEN_BYTES)
    session[GUEST_PROMPT_SESSION_KEY] = token
    return token


def get_guest_prompt_token(session: dict[str, Any]) -> str | None:
    """Return a valid existing guest identity without creating one during login."""
    token = session.get(GUEST_PROMPT_SESSION_KEY)
    if isinstance(token, str) and len(token) >= 32:
        return token
    return None


def _hash_guest_identifier(value: str) -> str:
    """Hash IP and cookie-derived identifiers before they reach the database."""
    secret = get_session_secret_key() or _GUEST_PROMPT_HASH_FALLBACK_SECRET
    global _fallback_secret_warning_logged
    if not get_session_secret_key() and not _fallback_secret_warning_logged:
        logger.warning(
            "FASTAPI_SECRET_KEY is unavailable; using the development guest prompt hash secret."
        )
        _fallback_secret_warning_logged = True
    return hmac.new(
        secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _guest_cookie_hash(guest_token: str) -> str:
    return _hash_guest_identifier(f"cookie:{guest_token}")


def _guest_ip_hash(client_ip: str) -> str:
    return _hash_guest_identifier(f"ip:{client_ip.strip().lower() or 'unknown'}")


def create_guest_shared_prompt(
    guest_token: str,
    client_ip: str,
    payload: SharedPromptCreateRequest,
) -> int:
    """Atomically enforce the guest quota and insert a text-only public prompt."""
    cookie_hash = _guest_cookie_hash(guest_token)
    ip_hash = _guest_ip_hash(client_ip)
    lock_keys = sorted(
        (
            f"guest-prompt:cookie:{cookie_hash}",
            f"guest-prompt:ip:{ip_hash}",
        )
    )

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            # Lock each independent quota key so changing only one identifier cannot
            # race two requests through the rolling 24-hour limit.
            for lock_key in lock_keys:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))

            cursor.execute(
                """
                SELECT GREATEST(
                    1,
                    CEIL(EXTRACT(EPOCH FROM (
                        MAX(created_at) + INTERVAL '24 hours' - NOW()
                    )))::INTEGER
                ) AS retry_after
                FROM guest_prompt_submissions
                WHERE created_at > NOW() - INTERVAL '24 hours'
                  AND (guest_cookie_hash = %s OR client_ip_hash = %s)
                HAVING MAX(created_at) IS NOT NULL
                """,
                (cookie_hash, ip_hash),
            )
            existing = cursor.fetchone()
            if existing:
                retry_after = int(existing.get("retry_after") or 1)
                raise GuestPromptLimitExceeded(retry_after)

            cursor.execute(
                """
                INSERT INTO prompts (
                    title, category, content, author, content_format, media_type,
                    attributes, attachments, input_examples, output_examples,
                    ai_model, description, user_id, is_public, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, 'ゲスト', 'prompt', 'text',
                    '{}'::jsonb, '[]'::jsonb, %s, %s, %s, %s, NULL, TRUE, NOW(), NOW()
                )
                RETURNING id
                """,
                (
                    payload.title,
                    payload.category,
                    payload.content,
                    payload.input_examples,
                    payload.output_examples,
                    payload.ai_model or None,
                    payload.description or None,
                ),
            )
            prompt_row = cursor.fetchone()
            if not prompt_row:
                raise RuntimeError("Guest shared prompt insert did not return an ID.")
            prompt_id = int(prompt_row["id"])

            cursor.execute(
                """
                INSERT INTO guest_prompt_submissions (
                    prompt_id, guest_cookie_hash, client_ip_hash, created_at
                )
                VALUES (%s, %s, %s, NOW())
                """,
                (prompt_id, cookie_hash, ip_hash),
            )
            conn.commit()
            return prompt_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def claim_guest_prompts_for_user(user_id: int, guest_token: str | None) -> list[int]:
    """Assign every unclaimed prompt from this browser cookie to the signed-in user."""
    if not guest_token:
        return []

    cookie_hash = _guest_cookie_hash(guest_token)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                WITH claimed_prompts AS (
                    UPDATE prompts AS p
                       SET user_id = %s,
                           author = (
                               SELECT COALESCE(username, 'ユーザー')
                               FROM users
                               WHERE id = %s
                           ),
                           updated_at = NOW()
                      FROM guest_prompt_submissions AS gps
                     WHERE gps.prompt_id = p.id
                       AND gps.guest_cookie_hash = %s
                       AND gps.claimed_at IS NULL
                       AND p.user_id IS NULL
                    RETURNING gps.id, p.id
                )
                UPDATE guest_prompt_submissions AS gps
                   SET claimed_by_user_id = %s,
                       claimed_at = NOW()
                  FROM claimed_prompts AS claimed
                 WHERE gps.id = claimed.id
                RETURNING gps.prompt_id
                """,
                (user_id, user_id, cookie_hash, user_id),
            )
            rows = cursor.fetchall() or []
            conn.commit()
            return [int(row[0]) for row in rows]
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
