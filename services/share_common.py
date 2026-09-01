"""Shared contracts for public links and token-backed share lifecycles.

Chat rooms, memos, and published prompts intentionally keep their own
repositories and persistence rules.  This module only owns the parts of a
share link that are common to those features: the public URL shape, token
generation/retry configuration, and the representation of an expirable or
revocable token.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from services.datetime_serialization import serialize_datetime_iso
from services.web_urls import build_frontend_url


class ShareContentKind(str, Enum):
    """Kinds of content that have a public Chat-Core URL."""

    CHAT = "chat"
    MEMO = "memo"
    PROMPT = "prompt"


_SHARE_PATH_PREFIXES: dict[ShareContentKind, str] = {
    ShareContentKind.CHAT: "/shared",
    ShareContentKind.MEMO: "/shared/memo",
    ShareContentKind.PROMPT: "/shared/prompt",
}

DEFAULT_SHARE_TOKEN_BYTES = 18
SHARED_TOKEN_MAX_COLLISION_RETRIES = 5
SHARED_TOKEN_RETRY_BACKOFF_SECONDS = 0.05
UNIQUE_VIOLATION_PGCODE = "23505"


def _coerce_content_kind(kind: ShareContentKind | str) -> ShareContentKind:
    if isinstance(kind, ShareContentKind):
        return kind
    try:
        return ShareContentKind(str(kind).strip().lower())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unsupported shared content kind: {kind!r}") from exc


def _validate_share_identifier(identifier: object) -> str:
    if identifier is None:
        raise ValueError("A share identifier is required.")
    value = str(identifier).strip()
    if not value:
        raise ValueError("A share identifier is required.")
    # Identifiers are tokens or numeric IDs.  Reject path/query delimiters so
    # callers cannot accidentally create a URL for a different resource.
    if any(character in value for character in "/?#"):
        raise ValueError("A share identifier must be a single URL path segment.")
    return value


def build_share_path(kind: ShareContentKind | str, identifier: object) -> str:
    """Build the canonical frontend path for a shared resource.

    The path forms are deliberately kept compatible with the existing public
    routes: ``/shared/{token}``, ``/shared/memo/{token}``, and
    ``/shared/prompt/{id}``.
    """

    content_kind = _coerce_content_kind(kind)
    return f"{_SHARE_PATH_PREFIXES[content_kind]}/{_validate_share_identifier(identifier)}"


def build_share_url(
    base_url: str,
    kind: ShareContentKind | str,
    identifier: object,
) -> str:
    """Build an absolute frontend URL for a shared resource."""

    return build_frontend_url(base_url, build_share_path(kind, identifier))


# Descriptive aliases make the contract easy to discover at call sites while
# retaining one implementation of path construction.
build_shared_content_path = build_share_path
build_shared_content_url = build_share_url


def generate_share_token(
    token_generator: Callable[[int], str] | None = None,
    *,
    token_bytes: int = DEFAULT_SHARE_TOKEN_BYTES,
) -> str:
    """Generate a share token using the shared size/configuration."""

    return (token_generator or secrets.token_urlsafe)(token_bytes)


def _sqlstate(exc: BaseException) -> str | None:
    """Read a PostgreSQL SQLSTATE through common SQLAlchemy wrappers."""

    current: BaseException | None = exc
    for _ in range(4):
        if current is None:
            return None
        value = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if value:
            return str(value)
        original = getattr(current, "orig", None)
        current = original if isinstance(original, BaseException) else None
    return None


def is_unique_violation(exc: BaseException) -> bool:
    """Return whether an exception represents PostgreSQL unique violation."""

    return _sqlstate(exc) == UNIQUE_VIOLATION_PGCODE


@dataclass(frozen=True)
class TokenShareLifecycle:
    """Serializable state shared by expirable/revocable token links.

    Chat links do not currently expose this state, but memo APIs and memo
    serializers use the same active/expired/revoked rules through this class.
    ``is_reused`` remains operation-specific and is therefore supplied when
    serializing rather than stored in the lifecycle itself.
    """

    share_token: str | None
    expires_at: datetime | None
    revoked_at: datetime | None

    @property
    def is_expired(self) -> bool:
        if not isinstance(self.expires_at, datetime):
            return False
        current = datetime.utcnow()
        expires_at = self.expires_at
        # PostgreSQL columns in older environments are naive UTC values, while
        # some callers/tests provide aware values.  Compare like with like.
        if expires_at.tzinfo is not None:
            current = datetime.now(timezone.utc)
        return expires_at <= current

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_active(self) -> bool:
        return bool(self.share_token) and not self.is_revoked and not self.is_expired

    def to_dict(self, *, is_reused: bool = False) -> dict[str, Any]:
        """Serialize the common lifecycle fields used by memo APIs."""

        return {
            "share_token": self.share_token or "",
            "expires_at": serialize_datetime_iso(self.expires_at),
            "revoked_at": serialize_datetime_iso(self.revoked_at),
            "is_expired": self.is_expired,
            "is_revoked": self.is_revoked,
            "is_active": self.is_active,
            "is_reused": is_reused,
        }

    def serialize(self, *, is_reused: bool = False) -> dict[str, Any]:
        """Alias for :meth:`to_dict` for serializer-oriented call sites."""

        return self.to_dict(is_reused=is_reused)

    @classmethod
    def from_values(
        cls,
        share_token: str | None,
        expires_at: datetime | None,
        revoked_at: datetime | None,
    ) -> "TokenShareLifecycle":
        return cls(share_token, expires_at, revoked_at)


def serialize_token_share_lifecycle(
    share_token: str | None,
    expires_at: datetime | None,
    revoked_at: datetime | None,
    *,
    is_reused: bool = False,
) -> dict[str, Any]:
    """Convenience wrapper for serializing :class:`TokenShareLifecycle`."""

    return TokenShareLifecycle.from_values(share_token, expires_at, revoked_at).to_dict(
        is_reused=is_reused,
    )


__all__ = [
    "DEFAULT_SHARE_TOKEN_BYTES",
    "SHARED_TOKEN_MAX_COLLISION_RETRIES",
    "SHARED_TOKEN_RETRY_BACKOFF_SECONDS",
    "ShareContentKind",
    "TokenShareLifecycle",
    "UNIQUE_VIOLATION_PGCODE",
    "build_share_path",
    "build_share_url",
    "build_shared_content_path",
    "build_shared_content_url",
    "generate_share_token",
    "is_unique_violation",
    "serialize_token_share_lifecycle",
]
