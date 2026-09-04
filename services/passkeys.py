from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import os
import secrets
import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import is_retryable_db_error, session_scope
from .repositories.passkey_repository import PasskeyRepository
from .web_constants import DEFAULT_FRONTEND_URL
from .web_urls import frontend_base_url

DEFAULT_PASSKEY_RP_NAME = "Chat Core"
PASSKEY_CHALLENGE_TTL_SECONDS = 300
PASSKEY_REGISTRATION_SESSION_KEY = "passkey_registration"
PASSKEY_AUTHENTICATION_SESSION_KEY = "passkey_authentication"
DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05


def get_passkey_rp_name() -> str:
    configured_name = (os.getenv("WEBAUTHN_RP_NAME") or os.getenv("PASSKEY_RP_NAME") or "").strip()
    return configured_name or DEFAULT_PASSKEY_RP_NAME


def get_passkey_rp_id(request: Request) -> str:
    configured_rp_id = (os.getenv("WEBAUTHN_RP_ID") or os.getenv("PASSKEY_RP_ID") or "").strip()
    if configured_rp_id:
        return configured_rp_id

    candidates = (frontend_base_url(), str(request.base_url), str(request.url))
    for candidate in candidates:
        hostname = urlsplit(candidate).hostname
        if isinstance(hostname, str) and hostname:
            return hostname
    return "localhost"


def get_passkey_origins(request: Request) -> list[str]:
    configured_env = (os.getenv("PASSKEY_ORIGINS") or os.getenv("WEBAUTHN_ORIGINS") or "").strip()
    if configured_env:
        explicit = [origin.strip() for origin in configured_env.split(",") if origin.strip()]
        if explicit:
            return explicit

    origins: list[str] = []
    candidates = (frontend_base_url(), str(request.base_url), str(request.url))
    for candidate in candidates:
        parts = urlsplit(candidate)
        if not parts.scheme or not parts.netloc:
            continue
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in origins:
            origins.append(origin)
    return origins or [DEFAULT_FRONTEND_URL]


def clear_passkey_session(session: dict[str, Any]) -> None:
    session.pop(PASSKEY_REGISTRATION_SESSION_KEY, None)
    session.pop(PASSKEY_AUTHENTICATION_SESSION_KEY, None)


def store_passkey_registration_ceremony(
    session: dict[str, Any], challenge: str
) -> dict[str, Any]:
    return _store_passkey_ceremony(session, PASSKEY_REGISTRATION_SESSION_KEY, challenge)


def store_passkey_authentication_ceremony(
    session: dict[str, Any], challenge: str
) -> dict[str, Any]:
    return _store_passkey_ceremony(session, PASSKEY_AUTHENTICATION_SESSION_KEY, challenge)


def get_passkey_registration_ceremony(session: dict[str, Any]) -> dict[str, Any] | None:
    return _load_passkey_ceremony(session.get(PASSKEY_REGISTRATION_SESSION_KEY))


def get_passkey_authentication_ceremony(session: dict[str, Any]) -> dict[str, Any] | None:
    return _load_passkey_ceremony(session.get(PASSKEY_AUTHENTICATION_SESSION_KEY))


def passkey_ceremony_is_expired(
    ceremony: dict[str, Any], *, now: int | None = None
) -> bool:
    issued_at = int(ceremony.get("issued_at") or 0)
    if issued_at <= 0:
        return True
    current_time = int(time.time()) if now is None else int(now)
    return current_time - issued_at > PASSKEY_CHALLENGE_TTL_SECONDS


def get_credential_lookup_id(credential: dict[str, Any]) -> str | None:
    raw_id = credential.get("rawId")
    if isinstance(raw_id, str) and raw_id:
        return raw_id
    credential_id = credential.get("id")
    if isinstance(credential_id, str) and credential_id:
        return credential_id
    return None


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
    if issued_at is None:
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


async def _run(
    operation: Callable[[PasskeyRepository], Awaitable[Any]],
    *,
    session: AsyncSession | None,
    commit: bool = False,
) -> Any:
    if session is not None:
        result = await operation(PasskeyRepository(session))
        return result

    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        try:
            async with session_scope() as db_session:
                result = await operation(PasskeyRepository(db_session))
                if commit:
                    await db_session.commit()
                return result
        except BaseException as exc:
            if commit and is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                await asyncio.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
    raise RuntimeError("Passkey database operation failed after retry attempts.")


async def list_passkeys_for_user(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _run(
        lambda repository: repository.list_for_user(int(user_id)),
        session=session,
    )


async def get_passkey_by_credential_id(
    credential_id: str,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    return await _run(
        lambda repository: repository.get_by_credential_id(credential_id),
        session=session,
    )


async def create_passkey(
    user_id: int,
    credential_id: str,
    public_key: str,
    sign_count: int,
    *,
    aaguid: str | None = None,
    credential_device_type: str | None = None,
    credential_backed_up: bool = False,
    label: str | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    normalized_label = (label or "").strip() or None
    normalized_aaguid = (aaguid or "").strip() or None
    normalized_device_type = (credential_device_type or "").strip() or None
    return await _run(
        lambda repository: repository.create(
            user_id=int(user_id),
            credential_id=credential_id,
            public_key=public_key,
            sign_count=int(sign_count),
            aaguid=normalized_aaguid,
            credential_device_type=normalized_device_type,
            credential_backed_up=bool(credential_backed_up),
            label=normalized_label,
        ),
        session=session,
        commit=True,
    )


async def update_passkey_usage(
    passkey_id: int,
    sign_count: int,
    *,
    credential_backed_up: bool | None = None,
    credential_device_type: str | None = None,
    session: AsyncSession | None = None,
) -> None:
    normalized_device_type = (credential_device_type or "").strip() or None
    await _run(
        lambda repository: repository.update_usage(
            passkey_id=int(passkey_id),
            sign_count=int(sign_count),
            credential_backed_up=credential_backed_up,
            credential_device_type=normalized_device_type,
        ),
        session=session,
        commit=True,
    )


async def delete_passkey(
    user_id: int,
    passkey_id: int,
    *,
    session: AsyncSession | None = None,
) -> bool:
    return await _run(
        lambda repository: repository.delete(
            user_id=int(user_id),
            passkey_id=int(passkey_id),
        ),
        session=session,
        commit=True,
    )
