import asyncio
import json
import os
import unittest
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from sqlalchemy.dialects import postgresql

from blueprints.chat.tasks import prompt_assist
from blueprints.chat.usage import get_usage_limits
from services.chat_use_case import ChatPostUseCase
from services.repositories.usage_repository import SubjectUsageTotals, UsageRepository
from services.usage_limits import (
    UsageLimitBlock,
    UsageTotals,
    check_usage_limit,
    get_usage_status,
    load_usage_limit_settings,
    set_usage_totals_reader,
    usage_limit_message,
    usage_periods,
)
from services.usage_metering import USAGE_TIMEZONE
from services.usage_subject import SYSTEM_USAGE_SUBJECT
from tests import _no_usage
from tests.helpers.request_helpers import build_request

_USD = 1_000_000_000
# 2026-09-23 12:00 JST (a Wednesday).
_NOW = datetime(2026, 9, 23, 3, 0, tzinfo=UTC)


def _jst(year, month, day):
    return datetime(year, month, day, tzinfo=USAGE_TIMEZONE)


class _TotalsMixin:
    def use_totals(self, *, daily=0.0, weekly=0.0, monthly=0.0):
        seen = []

        async def reader(subject_key, periods):
            seen.append((subject_key, periods))
            return UsageTotals(
                subject=SubjectUsageTotals(
                    daily_nano_usd=round(daily * _USD), weekly_nano_usd=round(weekly * _USD)
                ),
                monthly_total_nano_usd=round(monthly * _USD),
            )

        set_usage_totals_reader(reader)
        self.addCleanup(set_usage_totals_reader, _no_usage)
        return seen


class UsagePeriodTests(unittest.TestCase):
    def test_week_starts_on_monday_and_resets_at_midnight_japan_time(self):
        periods = usage_periods(_NOW)
        self.assertEqual(periods.day, date(2026, 9, 23))
        self.assertEqual(periods.week_start, date(2026, 9, 21))
        self.assertEqual(periods.month_start, date(2026, 9, 1))
        self.assertEqual(periods.next_day, _jst(2026, 9, 24))
        self.assertEqual(periods.next_week, _jst(2026, 9, 28))
        self.assertEqual(periods.next_month, _jst(2026, 10, 1))

    def test_japan_midnight_starts_the_next_day_before_utc_does(self):
        # 2026-09-27 15:00 UTC is Monday 00:00 JST.
        periods = usage_periods(datetime(2026, 9, 27, 15, 0, tzinfo=UTC))
        self.assertEqual(periods.day, date(2026, 9, 28))
        self.assertEqual(periods.week_start, date(2026, 9, 28))

    def test_december_rolls_over_to_january(self):
        periods = usage_periods(datetime(2026, 12, 31, 0, 0, tzinfo=UTC))
        self.assertEqual(periods.next_month, _jst(2027, 1, 1))


class UsageLimitSettingsTests(unittest.TestCase):
    def test_defaults_match_the_agreed_limits(self):
        with patch.dict(os.environ, {}, clear=False):
            for name in (
                "USAGE_USER_DAILY_LIMIT_USD",
                "USAGE_USER_WEEKLY_LIMIT_USD",
                "USAGE_GUEST_DAILY_LIMIT_USD",
                "USAGE_GUEST_WEEKLY_LIMIT_USD",
                "USAGE_MONTHLY_BUDGET_USD",
                "USAGE_MONTHLY_STOP_RATIO",
            ):
                os.environ.pop(name, None)
            settings = load_usage_limit_settings()

        self.assertEqual(settings.user_daily, round(1.50 * _USD))
        self.assertEqual(settings.user_weekly, round(6.00 * _USD))
        self.assertEqual(settings.guest_daily, round(0.03 * _USD))
        self.assertEqual(settings.guest_weekly, round(0.10 * _USD))
        # $30 の 90% = $27 で止める。 / Stop at 90% of $30 = $27.
        self.assertEqual(settings.monthly_stop, 27 * _USD)


class UsageLimitCheckTests(_TotalsMixin, unittest.TestCase):
    def test_user_under_every_limit_may_start(self):
        self.use_totals(daily=1.00, weekly=5.00, monthly=20)
        self.assertIsNone(asyncio.run(check_usage_limit("user:1", now=_NOW)))

    def test_daily_limit_blocks_until_midnight(self):
        self.use_totals(daily=1.50, weekly=1.50)
        block = asyncio.run(check_usage_limit("user:1", now=_NOW))
        self.assertEqual(block.reason, "daily")
        self.assertEqual(block.resets_at, _jst(2026, 9, 24))
        self.assertEqual(block.retry_after_seconds, 12 * 3600)

    def test_weekly_limit_is_reported_even_when_the_day_is_also_spent(self):
        self.use_totals(daily=2.00, weekly=6.00)
        block = asyncio.run(check_usage_limit("user:1", now=_NOW))
        self.assertEqual(block.reason, "weekly")
        self.assertEqual(block.resets_at, _jst(2026, 9, 28))

    def test_monthly_budget_stops_everyone_at_ninety_percent(self):
        self.use_totals(monthly=27)
        with self.assertLogs("services.usage_limits", level="WARNING"):
            block = asyncio.run(check_usage_limit("user:1", now=_NOW))
        self.assertEqual(block.reason, "monthly_budget")
        self.assertEqual(block.resets_at, _jst(2026, 10, 1))

        self.use_totals(monthly=26.99)
        self.assertIsNone(asyncio.run(check_usage_limit("user:1", now=_NOW)))

    def test_guests_have_their_own_smaller_limits(self):
        self.use_totals(daily=0.03, weekly=0.03)
        self.assertEqual(asyncio.run(check_usage_limit("guest:abc", now=_NOW)).reason, "daily")
        self.assertIsNone(asyncio.run(check_usage_limit("user:1", now=_NOW)))

    def test_system_usage_has_no_personal_limit(self):
        self.use_totals(daily=100, weekly=100)
        status = asyncio.run(get_usage_status(SYSTEM_USAGE_SUBJECT, now=_NOW))
        self.assertIsNone(status.daily)
        self.assertIsNone(asyncio.run(check_usage_limit(SYSTEM_USAGE_SUBJECT, now=_NOW)))

    def test_zero_disables_a_limit(self):
        self.use_totals(daily=5, weekly=5, monthly=1000)
        with patch.dict(
            os.environ,
            {
                "USAGE_USER_DAILY_LIMIT_USD": "0",
                "USAGE_USER_WEEKLY_LIMIT_USD": "0",
                "USAGE_MONTHLY_BUDGET_USD": "0",
            },
        ):
            self.assertIsNone(asyncio.run(check_usage_limit("user:1", now=_NOW)))

    def test_reader_receives_the_subject_and_japan_time_periods(self):
        seen = self.use_totals()
        asyncio.run(check_usage_limit("user:3", now=_NOW))
        [(subject_key, periods)] = seen
        self.assertEqual(subject_key, "user:3")
        self.assertEqual((periods.day, periods.week_start), (date(2026, 9, 23), date(2026, 9, 21)))

    def test_messages_are_localized(self):
        block = UsageLimitBlock(reason="weekly", resets_at=_NOW, retry_after_seconds=1)
        self.assertIn("今週", usage_limit_message(block, "ja"))
        self.assertIn("this week", usage_limit_message(block, "en"))


class UsageRepositoryTotalsTests(unittest.TestCase):
    def _compile(self, coroutine_factory, result):
        session = MagicMock()
        captured = []

        async def execute(statement):
            captured.append(statement)
            return result

        session.execute = execute
        value = asyncio.run(coroutine_factory(session))
        return value, str(captured[0].compile(dialect=postgresql.dialect()))

    def test_subject_totals_reads_the_day_and_the_week_in_one_query(self):
        result = MagicMock()
        result.one.return_value = (5, 12)
        totals, sql = self._compile(
            lambda session: UsageRepository().subject_totals(
                session, "user:1", day=date(2026, 9, 23), week_start=date(2026, 9, 21)
            ),
            result,
        )
        self.assertEqual(totals, SubjectUsageTotals(daily_nano_usd=5, weekly_nano_usd=12))
        self.assertIn("FILTER (WHERE api_usage_daily.usage_date =", sql)
        self.assertIn("api_usage_daily.subject_key =", sql)

    def test_total_cost_sums_every_subject_over_the_range(self):
        result = MagicMock()
        result.scalar_one.return_value = 42
        total, sql = self._compile(
            lambda session: UsageRepository().total_cost(
                session, start=date(2026, 9, 1), end=date(2026, 9, 23)
            ),
            result,
        )
        self.assertEqual(total, 42)
        self.assertNotIn("subject_key", sql)


_WEEKLY_BLOCK = UsageLimitBlock(reason="weekly", resets_at=_NOW, retry_after_seconds=3600)


class UsageLimitEnforcementTests(unittest.TestCase):
    def test_chat_post_refuses_before_the_guest_quota_and_before_storing_the_message(self):
        rate_limited = Mock(return_value="429 response")
        deps = SimpleNamespace(
            limits=SimpleNamespace(check_usage_limit=AsyncMock(return_value=_WEEKLY_BLOCK)),
            web=SimpleNamespace(jsonify_rate_limited=rate_limited),
        )
        use_case = ChatPostUseCase(deps, default_model="test-model", locale="en")
        use_case._parse_request = AsyncMock(return_value=None)
        use_case._consume_guest_daily_limit = AsyncMock(return_value=None)
        use_case._store_user_message = AsyncMock(return_value=None)
        request = build_request(method="POST", path="/api/chat", json_body={}, session={})

        response = asyncio.run(
            use_case.execute(
                request,
                auth_limit_service=None,
                llm_daily_limit_service=None,
                chat_generation_service=None,
            )
        )

        self.assertEqual(response, "429 response")
        use_case._consume_guest_daily_limit.assert_not_awaited()
        use_case._store_user_message.assert_not_awaited()
        message = rate_limited.call_args.args[0]
        self.assertIn("this week", message)
        self.assertEqual(rate_limited.call_args.kwargs["retry_after"], 3600)

    def test_prompt_assist_refuses_before_consuming_the_request_quota(self):
        request = build_request(
            method="POST",
            path="/api/prompt-assist",
            json_body={"target": "task_modal", "action": "generate_draft", "fields": {"title": "t"}},
            session={"user_id": 1},
        )
        with (
            patch("blueprints.chat.tasks._consume_prompt_assist_limits", return_value=(True, None)),
            patch("blueprints.chat.tasks.check_usage_limit", AsyncMock(return_value=_WEEKLY_BLOCK)),
            patch("blueprints.chat.tasks.consume_llm_daily_quota") as consume_quota,
            patch("blueprints.chat.tasks.create_prompt_assist_payload") as create_payload,
        ):
            response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "3600")
        self.assertIn("error", json.loads(response.body))
        consume_quota.assert_not_called()
        create_payload.assert_not_called()


class UsageLimitsEndpointTests(_TotalsMixin, unittest.TestCase):
    def _get(self, session):
        request = build_request(method="GET", path="/api/user/usage-limits", session=session)
        return asyncio.run(get_usage_limits(request))

    def test_requires_login(self):
        self.assertEqual(self._get({}).status_code, 401)

    def test_returns_shares_and_reset_times_but_never_amounts(self):
        seen = self.use_totals(daily=0.60, weekly=9.00, monthly=1)
        response = self._get({"user_id": 8})

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body)
        self.assertEqual(seen[0][0], "user:8")
        self.assertAlmostEqual(payload["daily"]["used_ratio"], 0.4)
        # 上限を超えても 1 で止める。 / Capped at 1 even when a turn overshoots.
        self.assertEqual(payload["weekly"]["used_ratio"], 1.0)
        self.assertTrue(payload["daily"]["resets_at"].endswith("+09:00"))
        self.assertFalse(payload["monthly_budget_exhausted"])
        self.assertNotIn("limit", json.dumps(payload))

    def test_disabled_limit_is_null(self):
        self.use_totals()
        with patch.dict(os.environ, {"USAGE_USER_DAILY_LIMIT_USD": "0"}):
            payload = json.loads(self._get({"user_id": 8}).body)
        self.assertIsNone(payload["daily"])
        self.assertIsNotNone(payload["weekly"])


if __name__ == "__main__":
    unittest.main()
