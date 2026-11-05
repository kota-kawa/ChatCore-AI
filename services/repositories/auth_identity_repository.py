"""認証 ID(メール・Google・Passkey 共通のユーザー行と user_auth_providers)の永続化境界。ログイン処理が使うユーザー情報を返す。

Persistence boundary for authentication identities and login-facing user data.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.avatar_storage import normalize_avatar_url
from services.models import User, UserAuthProvider

# 日本語: 認証ハンドラへ返すユーザー項目。ここに無い列(パスワード等)は外へ出さない。
# English: The user fields exposed to authentication handlers; columns not listed here never leave the repository.
_AUTH_USER_FIELDS = (
    "id",
    "email",
    "is_verified",
    "created_at",
    "username",
    "bio",
    "avatar_url",
    "llm_profile_context",
    "preferred_locale",
)


def _serialize_auth_user(
    user: User,
    provider: UserAuthProvider | None = None,
    *,
    google_provider_lookup: bool = False,
) -> dict[str, Any]:
    # 認証ハンドラが使う安定したpayloadを返す。
    """Return the stable payload consumed by authentication handlers."""

    payload = {field: getattr(user, field) for field in _AUTH_USER_FIELDS}
    # 旧 `/static/uploads/...` を現行の配信URLへ読み替えて返す。
    # Rewrite the legacy `/static/uploads/...` value to the served URL.
    payload["avatar_url"] = normalize_avatar_url(payload.get("avatar_url"))
    if provider is not None:
        payload.update(
            auth_provider=provider.provider,
            provider_user_id=provider.provider_user_id,
            provider_email=provider.provider_email,
        )
    elif google_provider_lookup:
        # 日本語: メール検索は Google アカウントの衝突確認にも使われる。メール ID を既存の Google ID と取り違えないよう、
        # Google 連携が無いときは provider 項目を明示的に None にする。
        # English: Email lookup also drives the Google account-conflict check. An email
        # identity must never be mistaken for an existing Google identity.
        payload.update(
            auth_provider=None,
            provider_user_id=None,
            provider_email=None,
        )
    return payload


class AuthIdentityRepository:
    # メール・Google・パスキー認証で共通のスキーマ契約を持つ。
    """Own the schema contract used by email, Google, and passkey login."""

    # 日本語: セッションの commit/rollback は呼び出し側(ユースケース)が持つ。ここでは flush と実行のみ行う。
    # English: Transaction commit/rollback belongs to the calling use case; this class only flushes and executes.

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        user = await self.session.scalar(select(User).where(User.id == int(user_id)))
        if user is None:
            return None
        return _serialize_auth_user(user)

    # 日本語: メールでの検索。Google 連携の有無を同時に引き(外部結合)、連携が無くても行は返す。
    # English: Looks up by email, outer-joining the Google provider row so users without a Google link are still returned.
    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        statement = (
            select(User, UserAuthProvider)
            .outerjoin(
                UserAuthProvider,
                (UserAuthProvider.user_id == User.id)
                & (UserAuthProvider.provider == "google"),
            )
            .where(User.email == email)
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        user, google_provider = row
        return _serialize_auth_user(
            user,
            google_provider,
            google_provider_lookup=True,
        )

    async def get_by_google_id(self, google_user_id: str) -> dict[str, Any] | None:
        statement = (
            select(User, UserAuthProvider)
            .join(UserAuthProvider, UserAuthProvider.user_id == User.id)
            .where(
                UserAuthProvider.provider == "google",
                UserAuthProvider.provider_user_id == google_user_id,
            )
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        user, provider = row
        return _serialize_auth_user(user, provider)

    # 日本語: (user_id, provider) の組を一意キーとして挿入し、既にあれば外部 ID とメールを更新する。
    # English: Upserts on the (user_id, provider) unique key, updating the external id and email when the row exists.
    async def _upsert_provider(
        self,
        *,
        user_id: int,
        provider: str,
        provider_user_id: str | None,
        provider_email: str | None,
    ) -> None:
        statement = (
            pg_insert(UserAuthProvider)
            .values(
                user_id=user_id,
                provider=provider,
                provider_user_id=provider_user_id,
                provider_email=provider_email,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "provider"],
                set_={
                    "provider_user_id": provider_user_id,
                    "provider_email": provider_email,
                    "updated_at": func.current_timestamp(),
                },
            )
        )
        await self.session.execute(statement)

    async def create(
        self,
        *,
        email: str,
        username: str,
        avatar_url: str,
        auth_provider: str,
        provider_user_id: str | None,
        provider_email: str | None,
        is_verified: bool,
        preferred_locale: str | None,
    ) -> int:
        # 日本語: プロバイダー情報は user_auth_providers だけに持たせる。User のコンストラクタに渡さないことで、
        # スキーマ移動があったときにこの認証境界で必ず気付けるようにする。
        # English: Provider metadata belongs only to user_auth_providers. Keeping it out
        # of the User constructor makes a schema move impossible to miss in
        # this dedicated authentication boundary.
        user = User(
            email=email,
            username=username,
            avatar_url=avatar_url,
            is_verified=is_verified,
            preferred_locale=preferred_locale,
        )
        self.session.add(user)
        await self.session.flush()
        if user.id is None:  # pragma: no cover - PostgreSQL always returns SERIAL id
            raise RuntimeError("User insert did not return an ID.")

        await self._upsert_provider(
            user_id=user.id,
            provider=auth_provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email,
        )
        return int(user.id)

    async def link_google_account(
        self,
        *,
        user_id: int,
        google_user_id: str,
        provider_email: str | None,
    ) -> None:
        await self._upsert_provider(
            user_id=user_id,
            provider="google",
            provider_user_id=google_user_id,
            provider_email=provider_email,
        )

    async def update_profile_from_google_if_unset(
        self,
        *,
        user_id: int,
        username: str | None,
        avatar_url: str | None,
        default_username: str,
        default_avatar_url: str,
    ) -> None:
        # 日本語: 既存の名前・アバターが空か既定値のままのときだけ Google の値で埋め、ユーザーが変更した内容は上書きしない。
        # English: Fills in the Google name/avatar only when the current value is empty or still the default, never overwriting user edits.
        user = await self.session.scalar(select(User).where(User.id == int(user_id)))
        if user is None:
            return

        next_username = user.username or default_username
        next_avatar_url = user.avatar_url or default_avatar_url
        if username and next_username.strip() in {"", default_username}:
            next_username = username
        if avatar_url and next_avatar_url.strip() in {"", default_avatar_url}:
            next_avatar_url = avatar_url

        await self.session.execute(
            update(User)
            .where(User.id == int(user_id))
            .values(username=next_username, avatar_url=next_avatar_url)
        )

    async def set_verified(self, user_id: int) -> None:
        await self.session.execute(
            update(User).where(User.id == int(user_id)).values(is_verified=True)
        )
