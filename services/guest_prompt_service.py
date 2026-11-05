"""未ログイン（ゲスト）による共有プロンプトの投稿の保存と、ログイン後の所有者の引き継ぎを扱う。
ゲストはセッション内のランダムなトークン（Cookie）と IP のハッシュで識別し、投稿は 24 時間に 1 件までに制限する。

Persistence and ownership transfer for unauthenticated shared prompts.
Guests are identified by a random session token (cookie) and a hashed IP, and limited to one post per rolling 24 hours.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.db import session_scope
from services.error_messages import ERROR_GUEST_PROMPT_LIMIT_REACHED
from services.prompt_embedding_service import schedule_prompt_embedding
from services.repositories.shared_content_repository import SharedContentRepository
from services.request_models import SharedPromptCreateRequest
from services.runtime_config import get_session_secret_key

logger = logging.getLogger(__name__)

# 日本語: ゲストのトークンをセッションに入れるキーと長さ、ハッシュ用の秘密鍵が無い開発環境向けの代替値。
# English: Session key and length for the guest token, and a fallback hash secret for development when no secret key is configured.
GUEST_PROMPT_SESSION_KEY = "guest_prompt_token"
GUEST_PROMPT_TOKEN_BYTES = 32
_GUEST_PROMPT_HASH_FALLBACK_SECRET = "chatcore-guest-prompt-hash-v1"
_fallback_secret_warning_logged = False


# 日本語: Cookie または IP が、直近の一定期間にすでに投稿していた場合の例外。retry_after は再試行までの秒数。
# English: Raised when the cookie or IP already posted within the rolling window; retry_after is the seconds to wait.
class GuestPromptLimitExceededError(ValueError):
    # CookieまたはIPが時間窓内に投稿済みであることを通知する。
    """Raised when the cookie or IP already posted within the rolling window."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(int(retry_after), 1)
        super().__init__(
            f"{ERROR_GUEST_PROMPT_LIMIT_REACHED}"
            f"{self.retry_after}秒ほど待ってから再試行してください。"
        )


def get_or_create_guest_prompt_token(session: dict[str, Any]) -> str:
    """Cookie に紐づくサーバー側セッションに、ランダムなゲスト識別子を保持して返す（無ければ作る）。

    Keep a random guest identity in the server-side session behind its cookie.
    """
    existing = session.get(GUEST_PROMPT_SESSION_KEY)
    if isinstance(existing, str) and len(existing) >= 32:
        return existing

    token = secrets.token_urlsafe(GUEST_PROMPT_TOKEN_BYTES)
    session[GUEST_PROMPT_SESSION_KEY] = token
    return token


def get_guest_prompt_token(session: dict[str, Any]) -> str | None:
    """有効なゲスト識別子が既にあれば返す。ログイン時に新しく作ることはしない。

    Return a valid existing guest identity without creating one during login.
    """
    token = session.get(GUEST_PROMPT_SESSION_KEY)
    if isinstance(token, str) and len(token) >= 32:
        return token
    return None


def _hash_guest_identifier(value: str) -> str:
    """IP や Cookie 由来の識別子を、DB に渡す前に HMAC-SHA256 でハッシュする。
    セッション秘密鍵が無い場合は開発用の代替値を使い、その旨を 1 回だけ警告する。

    Hash IP and cookie-derived identifiers before they reach the database.
    Without a session secret a development fallback is used, with a one-time warning.
    """
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


async def create_guest_shared_prompt(
    guest_token: str,
    client_ip: str,
    payload: SharedPromptCreateRequest,
    *,
    repository: SharedContentRepository | None = None,
    session: AsyncSession | None = None,
) -> int:
    """ゲストの投稿枠の確認と、テキストのみの公開プロンプトの登録を原子的に行い、プロンプト ID を返す。
    Cookie と IP の両方のキーを同じ順序でロックして競合を防ぎ、枠を超える場合は GuestPromptLimitExceededError にする。

    Atomically enforce the guest quota and insert a text-only public prompt.
    Both the cookie and IP keys are locked in a fixed order to avoid races; an exceeded quota raises GuestPromptLimitExceededError.
    """
    cookie_hash = _guest_cookie_hash(guest_token)
    ip_hash = _guest_ip_hash(client_ip)
    lock_keys = sorted(
        (
            f"guest-prompt:cookie:{cookie_hash}",
            f"guest-prompt:ip:{ip_hash}",
        )
    )

    prompt_repository = repository or SharedContentRepository()

    async def operation(active: AsyncSession) -> int:
        prompt_id, retry_after = await prompt_repository.create_guest_prompt(
            active,
            cookie_hash=cookie_hash,
            ip_hash=ip_hash,
            title=payload.title,
            category=payload.category,
            content=payload.content,
            input_examples=payload.input_examples,
            output_examples=payload.output_examples,
            ai_model=payload.ai_model,
            description=payload.description,
            lock_keys=lock_keys,
        )
        if retry_after is not None:
            raise GuestPromptLimitExceededError(retry_after)
        if prompt_id is None:
            raise RuntimeError("Guest shared prompt insert did not return an ID.")
        return prompt_id

    if session is None:
        async with session_scope() as owned_session, owned_session.begin():
            prompt_id = await operation(owned_session)
    else:
        prompt_id = await operation(session)
    schedule_prompt_embedding(prompt_id)
    return prompt_id


async def claim_guest_prompts_for_user(
    user_id: int,
    guest_token: str | None,
    *,
    repository: SharedContentRepository | None = None,
    session: AsyncSession | None = None,
) -> list[int]:
    """この Cookie でゲスト投稿された、まだ誰のものでもないプロンプトをすべて、ログインしたユーザーのものにする。

    Assign every unclaimed prompt from this browser cookie to the signed-in user.
    """
    if not guest_token:
        return []

    cookie_hash = _guest_cookie_hash(guest_token)
    prompt_repository = repository or SharedContentRepository()

    async def operation(active: AsyncSession) -> list[int]:
        return await prompt_repository.claim_guest_prompts(
            active,
            user_id=user_id,
            cookie_hash=cookie_hash,
        )

    if session is None:
        async with session_scope() as owned_session, owned_session.begin():
            return await operation(owned_session)
    return await operation(session)
