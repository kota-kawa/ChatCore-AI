"""MCP OAuth プロバイダー(クライアント登録、認可コード、付与(grant)、アクセス/リフレッシュトークン)の永続化境界。

プロトコルの検証やトークンの整形は services.mcp_oauth が持ち、ここは PostgreSQL への読み書きだけを担当する。
トークンと認可コードは平文でなくダイジェストで保存・照合する。

Persistence boundary for the MCP OAuth provider.
Tokens and authorization codes are stored and matched by digest, not plaintext.

The OAuth provider deliberately keeps protocol validation and token formatting
in ``services.mcp_oauth``.  This module owns only PostgreSQL persistence so a
single :class:`~sqlalchemy.ext.asyncio.AsyncSession` can cover each OAuth
use-case and its transaction boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import (
    McpOAuthAuthorizationCode,
    McpOAuthClient,
    McpOAuthGrant,
    McpOAuthToken,
    McpOAuthUserClient,
    User,
)

# ``mcp_oauth_clients.registration_method`` の CHECK 制約が許す値。
# The values allowed by the ``mcp_oauth_clients.registration_method`` check constraint.
DCR_REGISTRATION_METHOD = "dcr"
CIMD_REGISTRATION_METHOD = "cimd"
PRE_REGISTERED_REGISTRATION_METHOD = "pre_registered"


# 日本語: 以下の 3 つのレコードは、トークン/コードの行と、紐づく付与のユーザー ID・スコープ版数をまとめて Service へ返す入れ物。
# English: The three records below bundle a token/code row with the owning grant's user id and scope version for the service.
@dataclass(frozen=True)
class AuthorizationCodeRecord:
    code: McpOAuthAuthorizationCode
    user_id: int
    scope_version: int


@dataclass(frozen=True)
class RefreshTokenRecord:
    token: McpOAuthToken
    user_id: int
    scope_version: int


@dataclass(frozen=True)
class AccessTokenRecord:
    token: McpOAuthToken
    grant_id: UUID
    user_id: int
    scope_version: int


def _rowcount(result: Any) -> int:
    # PostgreSQLの更新結果から影響行数を読む。
    """Read the affected-row count exposed by PostgreSQL DML results."""
    return int(getattr(result, "rowcount", 0) or 0)


class McpOAuthRepository:
    # MCP OAuthサービスで使うORM/Core永続化操作。
    """ORM/Core persistence operations used by the MCP OAuth service."""

    # 日本語: 状態を持たないクラスで、各メソッドが呼び出し側の AsyncSession を受け取る(1 つのユースケースを 1 トランザクションで扱うため)。
    # English: Stateless; every method takes the caller's AsyncSession so a whole use case runs in one transaction.

    async def load_registered_client(
        self, session: AsyncSession, client_id: str
    ) -> McpOAuthClient | None:
        revoked_personal_client = exists(
            select(1).where(
                McpOAuthUserClient.client_id == McpOAuthClient.client_id,
                McpOAuthUserClient.revoked_at.is_not(None),
            )
        )
        return await session.scalar(
            select(McpOAuthClient).where(
                McpOAuthClient.client_id == client_id,
                # CIMD クライアントの正本はクライアント側のメタデータ文書であり、
                # ここに保存された行は外部キーの親としてだけ存在する。保存済みの
                # コピーを返すとリダイレクトURIの差し替えに追随できなくなるため、
                # 読み出し対象からは除外して毎回メタデータ文書を参照させる。
                # A CIMD client's source of truth is its client-hosted metadata
                # document; the stored row exists only as the foreign-key parent.
                # Returning the stored copy would freeze a rotated redirect URI,
                # so it is excluded and the document is re-read instead.
                McpOAuthClient.registration_method != CIMD_REGISTRATION_METHOD,
                ~revoked_personal_client,
            )
        )

    async def store_client(
        self,
        session: AsyncSession,
        *,
        client_id: str,
        metadata: dict[str, Any],
        encrypted_secret: str | None,
        registration_method: str,
    ) -> None:
        statement = insert(McpOAuthClient).values(
            client_id=client_id,
            client_metadata=metadata,
            client_secret_encrypted=encrypted_secret,
            registration_method=registration_method,
        )
        await session.execute(
            statement.on_conflict_do_nothing(index_elements=[McpOAuthClient.client_id])
        )

    # 日本語: 個人用クライアントは所有者の行があり、所有者本人かつ未失効のときだけ許可する。DCR/CIMD の
    # クライアントは所有者行を持たず誰でも使える。
    # English: A personal client has an owner row and is authorized only for its unrevoked owner; DCR/CIMD
    # clients have none and are open to all.
    async def user_client_is_authorized(
        self, session: AsyncSession, client_id: str, user_id: int
    ) -> bool:
        row = await session.scalar(
            select(McpOAuthUserClient).where(McpOAuthUserClient.client_id == client_id)
        )
        if row is None:
            # DCR/CIMDクライアントは利用者の所有物ではない。個人クライアントだけ明示的な所有者を持つ。
            # DCR/CIMD clients are not user-owned and can be authorized by any
            # verified user.  Personal clients have an explicit owner row.
            return True
        return row.revoked_at is None and row.user_id == user_id

    # 日本語: ユーザー行を FOR UPDATE でロックし、個人クライアントの上限確認と登録を直列化できるようにする。
    # English: Locks the user row (FOR UPDATE) so the personal-client cap check and registration can be serialized.
    async def lock_user(self, session: AsyncSession, user_id: int) -> User | None:
        return await session.scalar(
            select(User).where(User.id == user_id).with_for_update()
        )

    async def count_active_user_clients(self, session: AsyncSession, user_id: int) -> int:
        count = await session.scalar(
            select(func.count())
            .select_from(McpOAuthUserClient)
            .where(
                McpOAuthUserClient.user_id == user_id,
                McpOAuthUserClient.revoked_at.is_(None),
            )
        )
        return int(count or 0)

    async def insert_personal_client(
        self,
        session: AsyncSession,
        *,
        client_id: str,
        metadata: dict[str, Any],
        encrypted_secret: str | None,
        user_id: int,
        provider: str,
        label: str | None,
    ) -> None:
        await session.execute(
            insert(McpOAuthClient).values(
                client_id=client_id,
                client_metadata=metadata,
                client_secret_encrypted=encrypted_secret,
                registration_method=PRE_REGISTERED_REGISTRATION_METHOD,
            )
        )
        await session.execute(
            insert(McpOAuthUserClient).values(
                client_id=client_id,
                user_id=user_id,
                provider=provider,
                label=label,
            )
        )

    async def list_user_clients(
        self, session: AsyncSession, user_id: int
    ) -> list[tuple[McpOAuthUserClient, McpOAuthClient]]:
        result = await session.execute(
            select(McpOAuthUserClient, McpOAuthClient)
            .join(
                McpOAuthClient,
                McpOAuthClient.client_id == McpOAuthUserClient.client_id,
            )
            .where(
                McpOAuthUserClient.user_id == user_id,
                McpOAuthUserClient.revoked_at.is_(None),
            )
            .order_by(McpOAuthUserClient.created_at.desc())
        )
        return [(row[0], row[1]) for row in result.all()]

    async def update_user_client_label(
        self, session: AsyncSession, user_id: int, client_id: str, label: str | None
    ) -> bool:
        result = await session.execute(
            update(McpOAuthUserClient)
            .where(
                McpOAuthUserClient.client_id == client_id,
                McpOAuthUserClient.user_id == user_id,
                McpOAuthUserClient.revoked_at.is_(None),
            )
            .values(label=label)
        )
        return _rowcount(result) == 1

    # 日本語: 個人クライアントを失効し、そのクライアントとユーザーの付与・トークンもまとめて失効させる。すでに失効済みなら何もせず False。
    # English: Revokes a personal client together with its grants and tokens for that user; returns False
    # if it was already revoked or not found.
    async def revoke_user_client(
        self, session: AsyncSession, user_id: int, client_id: str
    ) -> bool:
        result = await session.execute(
            update(McpOAuthUserClient)
            .where(
                McpOAuthUserClient.client_id == client_id,
                McpOAuthUserClient.user_id == user_id,
                McpOAuthUserClient.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        if _rowcount(result) != 1:
            return False

        grant_ids = select(McpOAuthGrant.id).where(
            McpOAuthGrant.user_id == user_id,
            McpOAuthGrant.client_id == client_id,
        )
        await session.execute(
            update(McpOAuthToken)
            .where(
                McpOAuthToken.grant_id.in_(grant_ids),
                McpOAuthToken.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        await session.execute(
            update(McpOAuthGrant)
            .where(
                McpOAuthGrant.user_id == user_id,
                McpOAuthGrant.client_id == client_id,
                McpOAuthGrant.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        return True

    # 日本語: 付与(grant)と認可コードを作る。外部キーの順序のため付与を先に flush する(詳細は下のコメント)。
    # English: Creates the grant and its authorization code; the grant is flushed first because of the foreign key (see the comment below).
    async def create_grant_and_code(
        self,
        session: AsyncSession,
        *,
        grant_id: UUID,
        user_id: int,
        client_id: str,
        client_name: str,
        client_host: str,
        scopes: list[str],
        scope_version: int,
        code_digest: str,
        redirect_uri: str,
        code_challenge: str,
        resource: str,
        expires_at: datetime,
    ) -> None:
        session.add(
            McpOAuthGrant(
                id=grant_id,
                user_id=user_id,
                client_id=client_id,
                client_name=client_name,
                client_host=client_host,
                scopes=scopes,
                scope_version=scope_version,
            )
        )
        # 認可コードは付与(grant)を参照するが、両者に ORM の relationship が無いため、
        # まとめて flush すると SQLAlchemy はクラス名順（codes → grants）に INSERT し、
        # ``mcp_oauth_authorization_codes.grant_id`` の外部キーに違反する。
        # 先に付与だけを flush して親行を確定させる。
        # The code row points at the grant, but the two mappers have no ORM relationship, so a
        # single flush emits them in class-name order (codes before grants) and violates the
        # ``mcp_oauth_authorization_codes.grant_id`` foreign key. Flush the parent row first.
        await session.flush()
        session.add(
            McpOAuthAuthorizationCode(
                code_digest=code_digest,
                grant_id=grant_id,
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                scopes=scopes,
                resource=resource,
                expires_at=expires_at,
            )
        )
        await session.flush()

    async def is_user_verified(self, session: AsyncSession, user_id: int) -> bool:
        value = await session.scalar(select(User.is_verified).where(User.id == user_id))
        return bool(value)

    # 日本語: アクセストークンとリフレッシュトークンを 1 組で保存し、付与の last_used_at を更新する。
    # English: Stores the access/refresh token pair together and bumps the grant's last_used_at.
    async def insert_tokens(
        self,
        session: AsyncSession,
        *,
        grant_id: UUID,
        client_id: str,
        scopes: list[str],
        resource: str,
        access_token_digest: str,
        access_expires_at: datetime,
        refresh_token_digest: str,
        refresh_expires_at: datetime,
    ) -> None:
        session.add_all(
            [
                McpOAuthToken(
                    token_digest=access_token_digest,
                    grant_id=grant_id,
                    client_id=client_id,
                    token_type="access",
                    scopes=scopes,
                    resource=resource,
                    expires_at=access_expires_at,
                ),
                McpOAuthToken(
                    token_digest=refresh_token_digest,
                    grant_id=grant_id,
                    client_id=client_id,
                    token_type="refresh",
                    scopes=scopes,
                    resource=resource,
                    expires_at=refresh_expires_at,
                ),
            ]
        )
        await session.execute(
            update(McpOAuthGrant)
            .where(McpOAuthGrant.id == grant_id)
            .values(last_used_at=func.now())
        )
        await session.flush()

    # 日本語: 未使用・未期限切れで、付与が失効していない認可コードだけを返す。
    # English: Returns the authorization code only if it is unused, unexpired and its grant is not revoked.
    async def load_authorization_code(
        self, session: AsyncSession, client_id: str, code_digest: str
    ) -> AuthorizationCodeRecord | None:
        result = await session.execute(
            select(
                McpOAuthAuthorizationCode,
                McpOAuthGrant.user_id,
                McpOAuthGrant.scope_version,
            )
            .join(McpOAuthGrant, McpOAuthGrant.id == McpOAuthAuthorizationCode.grant_id)
            .where(
                McpOAuthAuthorizationCode.code_digest == code_digest,
                McpOAuthAuthorizationCode.client_id == client_id,
                McpOAuthAuthorizationCode.used_at.is_(None),
                McpOAuthAuthorizationCode.expires_at > func.now(),
                McpOAuthGrant.revoked_at.is_(None),
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        code, user_id, scope_version = row
        return AuthorizationCodeRecord(code, int(user_id), int(scope_version))

    # 日本語: used_at が空の行だけを更新するため、同じコードを二重に使うと 2 回目は False になる(認可コードは 1 回限り)。
    # English: Updates only rows with an empty used_at, so a second use of the same code returns False (codes are single-use).
    async def consume_authorization_code(
        self, session: AsyncSession, code_digest: str
    ) -> bool:
        result = await session.execute(
            update(McpOAuthAuthorizationCode)
            .where(
                McpOAuthAuthorizationCode.code_digest == code_digest,
                McpOAuthAuthorizationCode.used_at.is_(None),
            )
            .values(used_at=func.now())
        )
        return _rowcount(result) == 1

    # 日本語: 有効なリフレッシュトークンを、付与が失効しておらずユーザーが認証済みの場合に限って返す。for_update
    # で行ロックして回転の競合を防ぐ。
    # English: Returns a live refresh token only if its grant is not revoked and the user is verified; for_update
    # row-locks it against concurrent rotation.
    async def load_refresh_token(
        self, session: AsyncSession, client_id: str, token_digest: str, *, for_update: bool = False
    ) -> RefreshTokenRecord | None:
        statement = (
            select(McpOAuthToken, McpOAuthGrant.user_id, McpOAuthGrant.scope_version)
            .join(McpOAuthGrant, McpOAuthGrant.id == McpOAuthToken.grant_id)
            .join(User, User.id == McpOAuthGrant.user_id)
            .where(
                McpOAuthToken.token_digest == token_digest,
                McpOAuthToken.client_id == client_id,
                McpOAuthToken.token_type == "refresh",
                McpOAuthToken.revoked_at.is_(None),
                McpOAuthToken.expires_at > func.now(),
                McpOAuthGrant.revoked_at.is_(None),
                User.is_verified.is_(True),
            )
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.execute(statement)
        row = result.one_or_none()
        if row is None:
            return None
        token, user_id, scope_version = row
        return RefreshTokenRecord(token, int(user_id), int(scope_version))

    # 日本語: 回転済みの印(replaced_at)を付ける。coalesce で最初の時刻を保つので、再提示されても時刻は上書きされない。
    # English: Marks a refresh token as rotated; coalesce keeps the first replaced_at, so a re-presented token never moves it.
    async def mark_refresh_rotated(
        self, session: AsyncSession, token_digest: str, replaced_at: datetime
    ) -> bool:
        result = await session.execute(
            update(McpOAuthToken)
            .where(
                McpOAuthToken.token_digest == token_digest,
                McpOAuthToken.token_type == "refresh",
                McpOAuthToken.revoked_at.is_(None),
            )
            .values(
                replaced_at=func.coalesce(McpOAuthToken.replaced_at, replaced_at),
                last_used_at=func.now(),
            )
        )
        return _rowcount(result) == 1

    # 日本語: 有効なアクセストークンを、付与が失効しておらずユーザーが認証済みの場合に限って返す。
    # English: Returns a live access token only if its grant is not revoked and the user is verified.
    async def load_access_token(
        self, session: AsyncSession, token_digest: str
    ) -> AccessTokenRecord | None:
        result = await session.execute(
            select(
                McpOAuthToken,
                McpOAuthGrant.id,
                McpOAuthGrant.user_id,
                McpOAuthGrant.scope_version,
            )
            .join(McpOAuthGrant, McpOAuthGrant.id == McpOAuthToken.grant_id)
            .join(User, User.id == McpOAuthGrant.user_id)
            .where(
                McpOAuthToken.token_digest == token_digest,
                McpOAuthToken.token_type == "access",
                McpOAuthToken.revoked_at.is_(None),
                McpOAuthToken.expires_at > func.now(),
                McpOAuthGrant.revoked_at.is_(None),
                User.is_verified.is_(True),
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        token, grant_id, user_id, scope_version = row
        return AccessTokenRecord(token, grant_id, int(user_id), int(scope_version))

    async def touch_access_token(
        self, session: AsyncSession, token_digest: str, grant_id: UUID
    ) -> None:
        await session.execute(
            update(McpOAuthToken)
            .where(McpOAuthToken.token_digest == token_digest)
            .values(last_used_at=func.now())
        )
        await session.execute(
            update(McpOAuthGrant)
            .where(McpOAuthGrant.id == grant_id)
            .values(last_used_at=func.now())
        )

    # 日本語: 付与とそれに属する全トークン(アクセス/リフレッシュ)を失効させる。
    # English: Revokes a grant and every token (access and refresh) that belongs to it.
    async def revoke_grant_family(self, session: AsyncSession, grant_id: UUID) -> None:
        await session.execute(
            update(McpOAuthGrant)
            .where(
                McpOAuthGrant.id == grant_id,
                McpOAuthGrant.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        await session.execute(
            update(McpOAuthToken)
            .where(
                McpOAuthToken.grant_id == grant_id,
                McpOAuthToken.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )

    # 日本語: 失効していない接続(付与)を新しい順に返す。scope_version が現行より古い付与は除く。
    # English: Lists unrevoked connections (grants) newest first, excluding grants older than the given scope_version.
    async def list_connections(
        self, session: AsyncSession, user_id: int, scope_version: int
    ) -> list[McpOAuthGrant]:
        result = await session.scalars(
            select(McpOAuthGrant)
            .where(
                McpOAuthGrant.user_id == user_id,
                McpOAuthGrant.revoked_at.is_(None),
                McpOAuthGrant.scope_version >= scope_version,
            )
            .order_by(McpOAuthGrant.created_at.desc())
        )
        return list(result)

    async def revoke_connection(
        self, session: AsyncSession, user_id: int, grant_id: UUID
    ) -> bool:
        result = await session.execute(
            update(McpOAuthGrant)
            .where(
                McpOAuthGrant.id == grant_id,
                McpOAuthGrant.user_id == user_id,
                McpOAuthGrant.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        if _rowcount(result) != 1:
            return False
        await session.execute(
            update(McpOAuthToken)
            .where(
                McpOAuthToken.grant_id == grant_id,
                McpOAuthToken.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        return True

    async def update_connection_display_name(
        self, session: AsyncSession, user_id: int, grant_id: UUID, display_name: str | None
    ) -> bool:
        result = await session.execute(
            update(McpOAuthGrant)
            .where(
                McpOAuthGrant.id == grant_id,
                McpOAuthGrant.user_id == user_id,
                McpOAuthGrant.revoked_at.is_(None),
            )
            .values(display_name=display_name)
        )
        return _rowcount(result) == 1

    # 日本語: 提示されたトークン値の所属する付与全体を失効させる(トークンが無ければ何もしない)。
    # English: Revokes the whole grant family of a presented token value; does nothing if the token is unknown.
    async def revoke_token_value(self, session: AsyncSession, token_digest: str) -> None:
        grant_id = await session.scalar(
            select(McpOAuthToken.grant_id).where(
                McpOAuthToken.token_digest == token_digest
            )
        )
        if grant_id is not None:
            await self.revoke_grant_family(session, grant_id)
