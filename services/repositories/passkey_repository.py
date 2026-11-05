"""WebAuthn の資格情報(Passkey、user_passkeys)の一覧・取得・登録・利用更新・削除を永続化する。

services/passkeys.py から使われる。

Async SQLAlchemy persistence for WebAuthn credentials.
Used by services/passkeys.py.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import UserPasskey


# 日本語: Passkey 行を dict にする。user_id は既定で含めず、資格情報 ID から所有者を引く認証処理のときだけ含める。
# English: Serializes a passkey row. user_id is omitted by default and included only for the sign-in lookup that resolves the owner.
def _serialize_passkey(passkey: UserPasskey, *, include_user_id: bool = False) -> dict[str, Any]:
    fields = (
        "id",
        "user_id",
        "credential_id",
        "public_key",
        "sign_count",
        "aaguid",
        "credential_device_type",
        "credential_backed_up",
        "label",
        "created_at",
        "last_used_at",
    )
    payload = {field: getattr(passkey, field) for field in fields}
    if not include_user_id:
        payload.pop("user_id", None)
    return payload


class PasskeyRepository:
    """資格情報の登録と利用状況の更新を扱う永続化境界。

    Persistence boundary for credential registration and usage updates.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        statement = (
            select(UserPasskey)
            .where(UserPasskey.user_id == int(user_id))
            .order_by(UserPasskey.created_at.desc(), UserPasskey.id.desc())
        )
        passkeys = (await self.session.scalars(statement)).all()
        return [_serialize_passkey(passkey) for passkey in passkeys]

    async def get_by_credential_id(self, credential_id: str) -> dict[str, Any] | None:
        passkey = await self.session.scalar(
            select(UserPasskey).where(UserPasskey.credential_id == credential_id)
        )
        if passkey is None:
            return None
        return _serialize_passkey(passkey, include_user_id=True)

    async def create(
        self,
        *,
        user_id: int,
        credential_id: str,
        public_key: str,
        sign_count: int,
        aaguid: str | None,
        credential_device_type: str | None,
        credential_backed_up: bool,
        label: str | None,
    ) -> dict[str, Any] | None:
        passkey = UserPasskey(
            user_id=int(user_id),
            credential_id=credential_id,
            public_key=public_key,
            sign_count=int(sign_count),
            aaguid=aaguid,
            credential_device_type=credential_device_type,
            credential_backed_up=bool(credential_backed_up),
            label=label,
            last_used_at=func.current_timestamp(),
        )
        self.session.add(passkey)
        await self.session.flush()
        await self.session.refresh(passkey)
        return _serialize_passkey(passkey)

    # 日本語: 認証のたびに sign_count と最終利用時刻を更新する。バックアップ状態/デバイス種別は、値が得られたときだけ上書きする。
    # English: On each authentication, updates sign_count and last-used time; backup state and device type
    # are overwritten only when provided.
    async def update_usage(
        self,
        *,
        passkey_id: int,
        sign_count: int,
        credential_backed_up: bool | None,
        credential_device_type: str | None,
    ) -> None:
        values: dict[str, Any] = {
            "sign_count": int(sign_count),
            "last_used_at": func.current_timestamp(),
        }
        if credential_backed_up is not None:
            values["credential_backed_up"] = bool(credential_backed_up)
        if credential_device_type is not None:
            values["credential_device_type"] = credential_device_type

        await self.session.execute(
            update(UserPasskey)
            .where(UserPasskey.id == int(passkey_id))
            .values(**values)
        )

    # 日本語: 所有者が一致する Passkey だけを削除する。削除できたかを bool で返す。
    # English: Deletes a passkey only when it belongs to the user, and reports whether a row was removed.
    async def delete(self, *, user_id: int, passkey_id: int) -> bool:
        result = await self.session.execute(
            delete(UserPasskey).where(
                UserPasskey.id == int(passkey_id),
                UserPasskey.user_id == int(user_id),
            )
        )
        rowcount = getattr(result, "rowcount", 0)
        return bool(rowcount and rowcount > 0)
