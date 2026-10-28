"""Demo access codes: one code per recipient opens a sample-filled account for a limited period.

管理者が応募先ごとにコードを発行し、受け取った人がコードを入力すると、そのコード専用の
デモ用ユーザーに入る。初回の入力でユーザーを作ってサンプルデータを入れ、その時点から
DEMO_ACCESS_PERIOD が過ぎるか停止されたら、ユーザーごと削除する。コード本体は保存せず
digest だけを持つため、表示できるのは発行直後の1回だけ。
The admin issues one code per recipient. Entering it signs in to that code's own demo user,
created with sample data on the first entry; the user is deleted once DEMO_ACCESS_PERIOD has
passed since then or the code is revoked. Only the code's digest is stored, so the code can be
shown just once, right after it is issued.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from services.db import session_scope
from services.demo_sample_data import seed_demo_sample_data
from services.models import DemoAccessCode
from services.repositories.demo_access_repository import DemoAccessRepository
from services.repositories.usage_repository import UsageRepository
from services.repositories.user_repository import UserRepository
from services.usage_subject import user_usage_subject
from services.users import copy_default_tasks_for_user, create_user

logger = logging.getLogger(__name__)

DEMO_ACCESS_PERIOD = timedelta(days=30)
DEMO_USERNAME = "デモユーザー"
MAX_DEMO_LABEL_LENGTH = 120
# 1周期で削除するデモ用ユーザーの上限。残りは次の周期に回す。
# Cap on demo users deleted per cycle; the rest wait for the next cycle.
DEMO_PURGE_BATCH_SIZE = 50

# 読み間違えやすい i・l・o・0・1 を除いた 31 文字。12 文字で約 59 ビット。
# 31 characters without the easily confused i, l, o, 0 and 1; 12 of them give about 59 bits.
_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_CODE_PREFIX = "demo"
_CODE_GROUPS = 3
_CODE_GROUP_LENGTH = 4

DemoCodeStatus = Literal["unused", "active", "ended", "revoked"]


@dataclass(frozen=True, slots=True)
class DemoCodeSummary:
    id: int
    label: str
    status: DemoCodeStatus
    created_at: datetime
    first_used_at: datetime | None
    expires_at: datetime | None
    # 利用中のコードだけ値が入る。削除済みのユーザーの利用額は追わない。
    # Set only for an active code; a deleted user's spend is not tracked.
    used_nano_usd: int | None


@dataclass(frozen=True, slots=True)
class IssuedDemoCode:
    code: str
    summary: DemoCodeSummary


@dataclass(frozen=True, slots=True)
class DemoSignIn:
    user_id: int
    email: str
    expires_at: datetime


def generate_demo_code() -> str:
    groups = [
        "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_GROUP_LENGTH))
        for _ in range(_CODE_GROUPS)
    ]
    return "-".join([_CODE_PREFIX, *groups])


def demo_code_digest(raw_code: str) -> str:
    """Digest the code as entered, ignoring case, spaces and hyphens so a retyped code still matches."""

    canonical = "".join(character for character in raw_code.lower() if character.isalnum())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def demo_code_status(row: DemoAccessCode, now: datetime) -> DemoCodeStatus:
    if row.revoked_at is not None:
        return "revoked"
    if row.first_used_at is None:
        return "unused"
    # 期限切れのほか、利用者が自分でアカウントを削除した場合も終了。同じコードで作り直すと
    # 利用枠が戻ってしまうため、再利用させない。
    # Ended on expiry and also when the recipient deleted the account themselves: recreating it from
    # the same code would hand out a fresh allowance, so the code is not reusable.
    if row.user_id is None or row.expires_at is None or row.expires_at <= now:
        return "ended"
    return "active"


def _summary(row: DemoAccessCode, now: datetime, used: dict[str, int]) -> DemoCodeSummary:
    status = demo_code_status(row, now)
    used_nano_usd = None
    if status == "active" and row.user_id is not None:
        used_nano_usd = used.get(user_usage_subject(row.user_id), 0)
    return DemoCodeSummary(
        id=int(row.id),
        label=row.label,
        status=status,
        created_at=row.created_at,
        first_used_at=row.first_used_at,
        expires_at=row.expires_at,
        used_nano_usd=used_nano_usd,
    )


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


async def issue_demo_code(label: str, *, now: datetime | None = None) -> IssuedDemoCode:
    normalized_label = label.strip()[:MAX_DEMO_LABEL_LENGTH]
    if not normalized_label:
        raise ValueError("label is required")
    code = generate_demo_code()
    async with session_scope() as session:
        row = await DemoAccessRepository(session).insert(
            label=normalized_label,
            code_digest=demo_code_digest(code),
        )
        # コミットやセッションの終了で ORM の属性は失効するため、以下の関数も戻り値はその前に作る。
        # Committing or closing the session expires ORM attributes, so here and below the return
        # value is built before either happens.
        summary = _summary(row, _now(now), {})
        await session.commit()
    return IssuedDemoCode(code=code, summary=summary)


async def list_demo_codes(*, now: datetime | None = None) -> list[DemoCodeSummary]:
    moment = _now(now)
    async with session_scope() as session:
        rows = await DemoAccessRepository(session).list_all()
        active_subjects = [
            user_usage_subject(row.user_id)
            for row in rows
            if row.user_id is not None and demo_code_status(row, moment) == "active"
        ]
        used = await UsageRepository().lifetime_costs(session, active_subjects)
        return [_summary(row, moment, used) for row in rows]


async def revoke_demo_code(code_id: int, *, now: datetime | None = None) -> DemoCodeSummary | None:
    """Stop a code and delete its demo user; ``None`` when no such code exists."""

    moment = _now(now)
    async with session_scope() as session:
        row = await DemoAccessRepository(session).lock_by_id(code_id)
        if row is None:
            return None
        if row.revoked_at is None:
            row.revoked_at = moment
        if row.user_id is not None:
            await UserRepository(session).delete_account(row.user_id)
            row.user_id = None
        summary = _summary(row, moment, {})
        await session.commit()
    return summary


async def redeem_demo_code(raw_code: str, *, now: datetime | None = None) -> DemoSignIn | None:
    """Return the demo user to sign in as, creating it on first use; ``None`` for an unusable code."""

    moment = _now(now)
    async with session_scope() as session:
        row = await DemoAccessRepository(session).lock_by_digest(demo_code_digest(raw_code))
        if row is None:
            return None
        status = demo_code_status(row, moment)
        if status == "active" and row.user_id is not None and row.expires_at is not None:
            user = await UserRepository(session).get_user_by_id(row.user_id)
            if user is None:  # pragma: no cover - the FK clears user_id when the user goes
                return None
            return DemoSignIn(user_id=int(row.user_id), email=str(user["email"]), expires_at=row.expires_at)
        if status != "unused":
            return None

        # 連番の ID から作ると、他人がメールログインで同じアドレスを先に登録して初回利用を塞げるため、
        # 推測できない値にする。
        # Derived from the sequential id, the address could be registered first through email sign-in
        # and block the first use, so it is built from an unguessable value instead.
        email = f"demo-{secrets.token_hex(8)}@demo.invalid"
        user_id = await create_user(email, DEMO_USERNAME, is_verified=True, session=session)
        if user_id is None:  # pragma: no cover - create_user returns the SERIAL id
            raise RuntimeError("Demo user insert did not return an ID.")
        await copy_default_tasks_for_user(user_id, session=session)
        await seed_demo_sample_data(user_id, session=session)
        code_id = int(row.id)
        expires_at = moment + DEMO_ACCESS_PERIOD
        row.user_id = user_id
        row.first_used_at = moment
        row.expires_at = expires_at
        await session.commit()
    logger.info("Demo access code %s was used for the first time.", code_id)
    return DemoSignIn(user_id=user_id, email=email, expires_at=expires_at)


async def purge_expired_demo_accounts(*, now: datetime | None = None) -> int:
    """Delete demo users whose period has ended, in one bounded batch."""

    moment = _now(now)
    async with session_scope() as session:
        rows = await DemoAccessRepository(session).lock_expired(moment, limit=DEMO_PURGE_BATCH_SIZE)
        users = UserRepository(session)
        for row in rows:
            if row.user_id is not None:
                await users.delete_account(row.user_id)
                row.user_id = None
        await session.commit()
    deleted = len(rows)
    if deleted:
        logger.info("Deleted %s expired demo accounts.", deleted)
    return deleted
