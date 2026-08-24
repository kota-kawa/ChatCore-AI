"""Persistence boundary for the MCP OAuth provider.

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
    """Read the affected-row count exposed by PostgreSQL DML results."""
    return int(getattr(result, "rowcount", 0) or 0)


class McpOAuthRepository:
    """ORM/Core persistence operations used by the MCP OAuth service."""

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

    async def user_client_is_authorized(
        self, session: AsyncSession, client_id: str, user_id: int
    ) -> bool:
        row = await session.scalar(
            select(McpOAuthUserClient).where(McpOAuthUserClient.client_id == client_id)
        )
        if row is None:
            # DCR/CIMD clients are not user-owned and can be authorized by any
            # verified user.  Personal clients have an explicit owner row.
            return True
        return row.revoked_at is None and row.user_id == user_id

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
                registration_method="pre_registered",
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

    async def revoke_token_value(self, session: AsyncSession, token_digest: str) -> None:
        grant_id = await session.scalar(
            select(McpOAuthToken.grant_id).where(
                McpOAuthToken.token_digest == token_digest
            )
        )
        if grant_id is not None:
            await self.revoke_grant_family(session, grant_id)
