"""PostgreSQL integration coverage for demo access codes: first use, reuse, revoke, expiry and the allowance."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from services.db import dispose_engine, session_scope
from services.demo_access import (
    DEMO_ACCESS_PERIOD,
    issue_demo_code,
    list_demo_codes,
    purge_expired_demo_accounts,
    redeem_demo_code,
    revoke_demo_code,
)
from services.usage_limits import check_usage_limit, set_usage_totals_reader
from services.usage_subject import user_usage_subject
from services.users import delete_user_account
from tests import _no_usage

_NOW = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)
_USD = 1_000_000_000


@unittest.skipUnless(
    os.environ.get("DATABASE_URL"),
    "requires DATABASE_URL pointing at a PostgreSQL test database",
)
class DemoAccessIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.code_ids: list[int] = []
        self.user_ids: list[int] = []

    async def asyncTearDown(self) -> None:
        async with session_scope() as session, session.begin():
            for user_id in self.user_ids:
                await session.execute(
                    text("DELETE FROM api_usage_daily WHERE subject_key = :key"),
                    {"key": user_usage_subject(user_id)},
                )
                await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            for code_id in self.code_ids:
                await session.execute(text("DELETE FROM demo_access_codes WHERE id = :id"), {"id": code_id})
        await dispose_engine()

    async def _issue(self, label: str = "株式会社サンプル") -> str:
        issued = await issue_demo_code(label, now=_NOW)
        self.code_ids.append(issued.summary.id)
        return issued.code

    async def _redeem(self, code: str, now: datetime = _NOW):
        sign_in = await redeem_demo_code(code, now=now)
        if sign_in is not None and sign_in.user_id not in self.user_ids:
            self.user_ids.append(sign_in.user_id)
        return sign_in

    async def _count(self, table: str, user_id: int) -> int:
        async with session_scope() as session:
            return int(
                (
                    await session.execute(text(f"SELECT count(*) FROM {table} WHERE user_id = :id"), {"id": user_id})
                ).scalar_one()
            )

    async def _status(self, code_id: int, now: datetime = _NOW) -> str:
        [summary] = [item for item in await list_demo_codes(now=now) if item.id == code_id]
        return summary.status

    async def test_first_use_creates_a_sample_filled_account_and_later_uses_return_to_it(self) -> None:
        code = await self._issue()
        first = await self._redeem(code)
        assert first is not None
        self.assertEqual(first.expires_at, _NOW + DEMO_ACCESS_PERIOD)

        # 既定のタスクとサンプル一式が入っている。 / Bundled tasks and the whole sample set are present.
        self.assertGreater(await self._count("task_with_examples", first.user_id), 0)
        self.assertEqual(await self._count("projects", first.user_id), 1)
        self.assertEqual(await self._count("chat_rooms", first.user_id), 2)
        self.assertEqual(await self._count("memo_entries", first.user_id), 2)
        self.assertEqual(await self._count("context_facts", first.user_id), 2)
        self.assertEqual(await self._count("user_skills", first.user_id), 1)
        async with session_scope() as session:
            rooms_in_project = (
                await session.execute(
                    text("SELECT count(*) FROM chat_rooms WHERE user_id = :id AND project_id IS NOT NULL"),
                    {"id": first.user_id},
                )
            ).scalar_one()
            messages = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM chat_history h JOIN chat_rooms r ON r.id = h.chat_room_id "
                        "WHERE r.user_id = :id"
                    ),
                    {"id": first.user_id},
                )
            ).scalar_one()
        self.assertEqual(rooms_in_project, 1)
        self.assertEqual(messages, 6)

        # 別の端末から、表記ゆれのあるコードで入っても同じアカウントに戻り、期限は延びない。
        # Re-entering from elsewhere, even with different spacing and case, returns to the same
        # account and does not extend the period.
        again = await self._redeem(code.upper().replace("-", " "), now=_NOW + timedelta(days=3))
        assert again is not None
        self.assertEqual(again.user_id, first.user_id)
        self.assertEqual(again.expires_at, first.expires_at)
        self.assertEqual(await self._count("projects", first.user_id), 1)
        self.assertEqual(await self._status(self.code_ids[0]), "active")

    async def test_first_use_is_not_blocked_by_an_address_registered_in_advance(self) -> None:
        code = await self._issue()
        # 以前はコードの ID からアドレスを作っていたので、メールログインで先に登録できた。
        # The address used to come from the code id, so email sign-in could register it first.
        async with session_scope() as session, session.begin():
            squatter = (
                await session.execute(
                    text("INSERT INTO users (email, username) VALUES (:email, 'x') RETURNING id"),
                    {"email": f"demo-{self.code_ids[0]}@demo.invalid"},
                )
            ).scalar_one()
        self.user_ids.append(int(squatter))

        sign_in = await self._redeem(code)
        assert sign_in is not None
        self.assertNotEqual(sign_in.user_id, squatter)

    async def test_unknown_code_signs_in_nobody(self) -> None:
        await self._issue()
        self.assertIsNone(await self._redeem("demo-zzzz-zzzz-zzzz"))

    async def test_revoking_deletes_the_account_and_closes_the_code(self) -> None:
        code = await self._issue()
        sign_in = await self._redeem(code)
        assert sign_in is not None

        summary = await revoke_demo_code(self.code_ids[0], now=_NOW + timedelta(days=1))
        assert summary is not None
        self.assertEqual(summary.status, "revoked")
        self.assertEqual(await self._count("projects", sign_in.user_id), 0)
        self.assertIsNone(await self._redeem(code, now=_NOW + timedelta(days=1)))

    async def test_purge_deletes_only_accounts_past_their_period(self) -> None:
        expiring = await self._issue("期限切れ")
        running = await self._issue("利用中")
        expiring_user = await self._redeem(expiring)
        running_user = await self._redeem(running, now=_NOW + timedelta(days=10))
        assert expiring_user is not None and running_user is not None

        after_period = _NOW + DEMO_ACCESS_PERIOD
        self.assertGreaterEqual(await purge_expired_demo_accounts(now=after_period), 1)

        self.assertEqual(await self._count("projects", expiring_user.user_id), 0)
        self.assertEqual(await self._count("projects", running_user.user_id), 1)
        self.assertEqual(await self._status(self.code_ids[0], after_period), "ended")
        self.assertEqual(await self._status(self.code_ids[1], after_period), "active")
        self.assertIsNone(await self._redeem(expiring, now=after_period))

    async def test_an_account_the_recipient_deleted_is_not_recreated(self) -> None:
        code = await self._issue()
        sign_in = await self._redeem(code)
        assert sign_in is not None
        self.assertTrue(await delete_user_account(sign_in.user_id))

        self.assertIsNone(await self._redeem(code, now=_NOW + timedelta(days=1)))
        self.assertEqual(await self._status(self.code_ids[0]), "ended")

    async def test_allowance_counts_every_day_of_the_period(self) -> None:
        set_usage_totals_reader(None)
        self.addCleanup(set_usage_totals_reader, _no_usage)
        code = await self._issue()
        sign_in = await self._redeem(code, now=datetime.now(UTC))
        assert sign_in is not None
        subject = user_usage_subject(sign_in.user_id)

        # 日・週の上限（$1.50 / $6）には届かない額を、日をまたいで合計 $1.50 使う。
        # Spend $1.50 in total across days, never reaching the daily or weekly limit on its own.
        today = datetime.now(UTC).date()
        async with session_scope() as session, session.begin():
            for days_ago, cost in ((8, 0.70), (1, 0.80)):
                await session.execute(
                    text(
                        "INSERT INTO api_usage_daily (subject_key, usage_date, resource, cost_nano_usd) "
                        "VALUES (:subject, :day, 'test-model', :cost)"
                    ),
                    {"subject": subject, "day": today - timedelta(days=days_ago), "cost": round(cost * _USD)},
                )

        block = await check_usage_limit(subject)
        assert block is not None
        self.assertEqual(block.reason, "demo")
        [summary] = [item for item in await list_demo_codes() if item.id == self.code_ids[0]]
        self.assertEqual(summary.used_nano_usd, round(1.50 * _USD))


if __name__ == "__main__":
    unittest.main()
