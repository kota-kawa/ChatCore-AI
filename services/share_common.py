"""公開リンクとトークン式共有の有効期限・失効の共通契約。

チャットルーム・メモ・公開プロンプトは、それぞれ独自のリポジトリと永続化規則を持つ。このモジュールが持つのは、
どの機能でも共通する共有リンクの部分だけ: 公開 URL の形、トークン生成と衝突時の再試行設定、
期限切れ・失効しうるトークンの表現。

Shared contracts for public links and token-backed share lifecycles.

Chat rooms, memos, and published prompts intentionally keep their own
repositories and persistence rules.  This module only owns the parts of a
share link that are common to those features: the public URL shape, token
generation/retry configuration, and the representation of an expirable or
revocable token.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from services.datetime_serialization import serialize_datetime_iso
from services.web_constants import DEFAULT_FRONTEND_URL
from services.web_urls import build_frontend_url, frontend_base_url


class ShareContentKind(str, Enum):
    """公開 Chat-Core URL を持つコンテンツの種類。

    Kinds of content that have a public Chat-Core URL.
    """

    CHAT = "chat"
    MEMO = "memo"
    PROMPT = "prompt"


# 日本語: 種類ごとのフロントエンド側の公開パスの接頭辞。
# English: Frontend public path prefix for each content kind.
_SHARE_PATH_PREFIXES: dict[ShareContentKind, str] = {
    ShareContentKind.CHAT: "/shared",
    ShareContentKind.MEMO: "/shared/memo",
    ShareContentKind.PROMPT: "/shared/prompt",
}

# 日本語: トークン生成のバイト数、一意制約の衝突時の再試行回数と待ち時間、PostgreSQL の一意制約違反コード。
# English: Token size in bytes, retry count and backoff on a unique-constraint collision, and the PostgreSQL unique violation code.
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
    # 日本語: 識別子はトークンか数値 ID。パスやクエリの区切りを弾き、別のリソースの URL を誤って作らないようにする。
    # English: Identifiers are tokens or numeric IDs.  Reject path/query delimiters so
    # callers cannot accidentally create a URL for a different resource.
    if any(character in value for character in "/?#"):
        raise ValueError("A share identifier must be a single URL path segment.")
    return value


def build_share_path(kind: ShareContentKind | str, identifier: object) -> str:
    """共有リソースのフロントエンド側の正規パスを作る。

    パスの形は既存の公開ルートと互換に保つ: ``/shared/{token}``、``/shared/memo/{token}``、``/shared/prompt/{id}``。

    Build the canonical frontend path for a shared resource.

    The path forms are deliberately kept compatible with the existing public
    routes: ``/shared/{token}``, ``/shared/memo/{token}``, and
    ``/shared/prompt/{id}``.
    """

    content_kind = _coerce_content_kind(kind)
    return f"{_SHARE_PATH_PREFIXES[content_kind]}/{_validate_share_identifier(identifier)}"


def resolve_share_base_url() -> str:
    """すべての共有リンクの元になる公開ベース URL を 1 つに決める。

    Resolve the one public base URL that every share link is built from.

    共有リンクはフロントエンドのページを指すため ``FRONTEND_URL`` を正本と
    する。MCP 用の公開URLだけを設定した構成でリンクが localhost に退化しない
    よう、``FRONTEND_URL`` が既定値のままのときだけ ``MCP_PUBLIC_BASE_URL``
    を使う（この値の厳格な検証は MCP エンドポイント側の
    ``services/mcp_config.py`` が担う）。
    """

    frontend = frontend_base_url().strip()
    if frontend and frontend.rstrip("/") != DEFAULT_FRONTEND_URL:
        return frontend
    mcp_public = (os.getenv("MCP_PUBLIC_BASE_URL") or "").strip()
    return mcp_public or frontend or DEFAULT_FRONTEND_URL


def build_share_url(
    base_url: str,
    kind: ShareContentKind | str,
    identifier: object,
) -> str:
    """共有リソースのフロントエンド絶対 URL を作る。

    Build an absolute frontend URL for a shared resource.
    """

    return build_frontend_url(base_url, build_share_path(kind, identifier))


def build_public_share_url(kind: ShareContentKind | str, identifier: object) -> str:
    """公開ベース URL を解決して、正規の共有 URL を作る。

    Build the canonical share URL, resolving the public base URL once.
    """

    return build_share_url(resolve_share_base_url(), kind, identifier)


# 日本語: 呼び出し側で意味が伝わりやすい別名。パス組み立ての実装は 1 つのまま共有する。
# English: Descriptive aliases make the contract easy to discover at call sites while
# retaining one implementation of path construction.
build_shared_content_path = build_share_path
build_shared_content_url = build_share_url


def generate_share_token(
    token_generator: Callable[[int], str] | None = None,
    *,
    token_bytes: int = DEFAULT_SHARE_TOKEN_BYTES,
) -> str:
    """共通のサイズ設定で共有トークンを生成する。token_generator はテストで差し替えるための引数。

    Generate a share token using the shared size/configuration.
    """

    return (token_generator or secrets.token_urlsafe)(token_bytes)


def _sqlstate(exc: BaseException) -> str | None:
    """SQLAlchemy などのラッパー越しに PostgreSQL の SQLSTATE を読み取る。

    Read a PostgreSQL SQLSTATE through common SQLAlchemy wrappers.
    """

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
    """例外が PostgreSQL の一意制約違反かどうかを返す。トークン衝突時の再試行判定に使う。

    Return whether an exception represents PostgreSQL unique violation.
    """

    return _sqlstate(exc) == UNIQUE_VIOLATION_PGCODE


@dataclass(frozen=True)
class TokenShareLifecycle:
    """期限切れ・失効しうるトークンリンクに共通する、シリアライズ可能な状態。

    チャットのリンクは今のところこの状態を公開していないが、メモの API とシリアライザは、この
    クラスを通じて同じ「有効／期限切れ／失効」の規則を使う。``is_reused`` は操作ごとに決まる値なので、
    ライフサイクルには持たせず、シリアライズ時に渡す。

    Serializable state shared by expirable/revocable token links.

    Chat links do not currently expose this state, but memo APIs and memo
    serializers use the same active/expired/revoked rules through this class.
    ``is_reused`` remains operation-specific and is therefore supplied when
    serializing rather than stored in the lifecycle itself.
    """

    share_token: str | None
    expires_at: datetime | None
    revoked_at: datetime | None

    # 日本語: 期限が過ぎているか。期限未設定なら期限切れではない。
    # English: Whether the expiry has passed; no expiry means not expired.
    @property
    def is_expired(self) -> bool:
        if not isinstance(self.expires_at, datetime):
            return False
        current = datetime.utcnow()
        expires_at = self.expires_at
        # 日本語: 古い環境の PostgreSQL 列は naive な UTC で、呼び出し側やテストが aware な値を渡すこともあるため、同じ種類同士で比べる。
        # English: PostgreSQL columns in older environments are naive UTC values, while
        # some callers/tests provide aware values.  Compare like with like.
        if expires_at.tzinfo is not None:
            current = datetime.now(UTC)
        return expires_at <= current

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    # 日本語: トークンがあり、失効も期限切れもしていなければ有効。
    # English: Active when a token exists and it is neither revoked nor expired.
    @property
    def is_active(self) -> bool:
        return bool(self.share_token) and not self.is_revoked and not self.is_expired

    def to_dict(self, *, is_reused: bool = False) -> dict[str, Any]:
        """メモ API が使う共通のライフサイクル項目を辞書にする。

        Serialize the common lifecycle fields used by memo APIs.
        """

        return {
            "share_token": self.share_token or "",
            "expires_at": serialize_datetime_iso(self.expires_at),
            "revoked_at": serialize_datetime_iso(self.revoked_at),
            "is_expired": self.is_expired,
            "is_revoked": self.is_revoked,
            "is_active": self.is_active,
            "is_reused": is_reused,
        }

    @classmethod
    def from_values(
        cls,
        share_token: str | None,
        expires_at: datetime | None,
        revoked_at: datetime | None,
    ) -> TokenShareLifecycle:
        return cls(share_token, expires_at, revoked_at)


def serialize_token_share_lifecycle(
    share_token: str | None,
    expires_at: datetime | None,
    revoked_at: datetime | None,
    *,
    is_reused: bool = False,
) -> dict[str, Any]:
    """:class:`TokenShareLifecycle` をそのまま辞書にする簡易ラッパー。

    Convenience wrapper for serializing :class:`TokenShareLifecycle`.
    """

    return TokenShareLifecycle.from_values(share_token, expires_at, revoked_at).to_dict(
        is_reused=is_reused,
    )


__all__ = [
    "DEFAULT_SHARE_TOKEN_BYTES",
    "SHARED_TOKEN_MAX_COLLISION_RETRIES",
    "SHARED_TOKEN_RETRY_BACKOFF_SECONDS",
    "UNIQUE_VIOLATION_PGCODE",
    "ShareContentKind",
    "TokenShareLifecycle",
    "build_public_share_url",
    "build_share_path",
    "build_share_url",
    "build_shared_content_path",
    "build_shared_content_url",
    "generate_share_token",
    "is_unique_violation",
    "resolve_share_base_url",
    "serialize_token_share_lifecycle",
]
