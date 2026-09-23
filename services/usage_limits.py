"""Per-user daily/weekly cost limits and the system-wide monthly budget.

`services.usage_metering` が記録した料金を読み、AI 機能を始める前に判定します。
判定は処理の開始時だけ行うため、実行中のターンは上限を少し超えて終わることがあります。
全体の月予算は、その超過と使用量の見積もり誤差を吸収できるよう予算の手前（既定 90%）で
止めます。
Reads the costs recorded by `services.usage_metering` and decides before an AI feature
starts. The check runs only at the start, so a turn already in flight may finish slightly
over a limit; the monthly budget therefore stops short of the budget itself (90% by
default) to absorb that overshoot and any estimation error.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from services.env_settings import env_float
from services.i18n import translate
from services.repositories.usage_repository import SubjectUsageTotals
from services.usage_metering import USAGE_TIMEZONE
from services.usage_subject import SYSTEM_USAGE_SUBJECT, current_usage_subject

logger = logging.getLogger(__name__)

_NANO_USD_PER_USD = 1_000_000_000

LimitReason = Literal["daily", "weekly", "monthly_budget"]


@dataclass(frozen=True, slots=True)
class UsageLimitSettings:
    """Configured limits in nano-dollars; ``0`` means the limit is disabled."""

    user_daily: int
    user_weekly: int
    guest_daily: int
    guest_weekly: int
    monthly_stop: int


def _usd_env(name: str, default: float) -> int:
    amount = env_float(name, default, minimum=0.0, minimum_inclusive=True, warn_on_invalid=True)
    return round(amount * _NANO_USD_PER_USD)


def load_usage_limit_settings() -> UsageLimitSettings:
    """Read the limits from the environment on every call so changes need no reload."""

    ratio = min(env_float("USAGE_MONTHLY_STOP_RATIO", 0.9, warn_on_invalid=True), 1.0)
    return UsageLimitSettings(
        user_daily=_usd_env("USAGE_USER_DAILY_LIMIT_USD", 1.50),
        user_weekly=_usd_env("USAGE_USER_WEEKLY_LIMIT_USD", 6.00),
        guest_daily=_usd_env("USAGE_GUEST_DAILY_LIMIT_USD", 0.03),
        guest_weekly=_usd_env("USAGE_GUEST_WEEKLY_LIMIT_USD", 0.10),
        monthly_stop=int(_usd_env("USAGE_MONTHLY_BUDGET_USD", 30.0) * ratio),
    )


@dataclass(frozen=True, slots=True)
class UsageTotals:
    """Costs in nano-dollars that the limits are compared against."""

    subject: SubjectUsageTotals
    monthly_total_nano_usd: int


@dataclass(frozen=True, slots=True)
class UsagePeriods:
    """The Japan-time calendar windows that contain one moment."""

    day: date
    week_start: date
    month_start: date
    next_day: datetime
    next_week: datetime
    next_month: datetime


def usage_periods(now: datetime | None = None) -> UsagePeriods:
    """Return the day, the Monday-start week and the month containing ``now`` (Japan time)."""

    local_now = (now or datetime.now(UTC)).astimezone(USAGE_TIMEZONE)
    day = local_now.date()
    week_start = day - timedelta(days=day.weekday())
    month_start = day.replace(day=1)
    next_month_start = (
        date(day.year + 1, 1, 1) if day.month == 12 else date(day.year, day.month + 1, 1)
    )

    def midnight(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=USAGE_TIMEZONE)

    return UsagePeriods(
        day=day,
        week_start=week_start,
        month_start=month_start,
        next_day=midnight(day + timedelta(days=1)),
        next_week=midnight(week_start + timedelta(days=7)),
        next_month=midnight(next_month_start),
    )


UsageTotalsReader = Callable[[str, UsagePeriods], Awaitable[UsageTotals]]


async def _read_usage_totals(subject_key: str, periods: UsagePeriods) -> UsageTotals:
    from services.db import session_scope
    from services.repositories.usage_repository import UsageRepository

    repository = UsageRepository()
    async with session_scope() as session:
        subject = await repository.subject_totals(
            session, subject_key, day=periods.day, week_start=periods.week_start
        )
        monthly = await repository.total_cost(session, start=periods.month_start, end=periods.day)
    return UsageTotals(subject=subject, monthly_total_nano_usd=monthly)


_usage_totals_reader: UsageTotalsReader = _read_usage_totals


def set_usage_totals_reader(reader: UsageTotalsReader | None) -> None:
    """Replace where totals are read from; ``None`` restores the database reader."""

    global _usage_totals_reader
    _usage_totals_reader = reader or _read_usage_totals


@dataclass(frozen=True, slots=True)
class UsageWindow:
    """One personal limit window."""

    used_nano_usd: int
    limit_nano_usd: int
    resets_at: datetime

    @property
    def exhausted(self) -> bool:
        return self.limit_nano_usd > 0 and self.used_nano_usd >= self.limit_nano_usd


@dataclass(frozen=True, slots=True)
class UsageStatus:
    """Where one subject stands against its limits and the monthly budget."""

    daily: UsageWindow | None
    weekly: UsageWindow | None
    monthly_budget_exhausted: bool
    monthly_resets_at: datetime


@dataclass(frozen=True, slots=True)
class UsageLimitBlock:
    """Why a new AI request is refused and when it may be retried."""

    reason: LimitReason
    resets_at: datetime
    retry_after_seconds: int


def _personal_limits(subject_key: str, settings: UsageLimitSettings) -> tuple[int, int] | None:
    if subject_key == SYSTEM_USAGE_SUBJECT:
        return None
    if subject_key.startswith("user:"):
        return settings.user_daily, settings.user_weekly
    return settings.guest_daily, settings.guest_weekly


async def get_usage_status(
    subject_key: str | None = None,
    *,
    now: datetime | None = None,
) -> UsageStatus:
    """Return the current subject's standing against its limits."""

    subject_key = subject_key or current_usage_subject()
    settings = load_usage_limit_settings()
    periods = usage_periods(now)
    totals = await _usage_totals_reader(subject_key, periods)

    limits = _personal_limits(subject_key, settings)
    daily = weekly = None
    if limits is not None:
        daily = UsageWindow(totals.subject.daily_nano_usd, limits[0], periods.next_day)
        weekly = UsageWindow(totals.subject.weekly_nano_usd, limits[1], periods.next_week)
    return UsageStatus(
        daily=daily,
        weekly=weekly,
        monthly_budget_exhausted=(
            settings.monthly_stop > 0 and totals.monthly_total_nano_usd >= settings.monthly_stop
        ),
        monthly_resets_at=periods.next_month,
    )


def _block(reason: LimitReason, resets_at: datetime, now: datetime) -> UsageLimitBlock:
    seconds = int((resets_at - now).total_seconds())
    return UsageLimitBlock(reason=reason, resets_at=resets_at, retry_after_seconds=max(seconds, 1))


async def check_usage_limit(
    subject_key: str | None = None,
    *,
    now: datetime | None = None,
) -> UsageLimitBlock | None:
    """Return why a new AI request must be refused, or ``None`` when it may start."""

    moment = now or datetime.now(UTC)
    status = await get_usage_status(subject_key, now=moment)
    # 全体の予算が最優先。個人の枠が残っていても止める。
    # The shared budget comes first: it stops everyone, whatever their own allowance.
    if status.monthly_budget_exhausted:
        logger.warning("Monthly API budget reached; refusing new AI requests until next month.")
        return _block("monthly_budget", status.monthly_resets_at, moment)
    # 週の枠が尽きていれば、日が変わっても使えないので週の方を案内する。
    # When the weekly allowance is gone a new day does not help, so report the week.
    if status.weekly is not None and status.weekly.exhausted:
        return _block("weekly", status.weekly.resets_at, moment)
    if status.daily is not None and status.daily.exhausted:
        return _block("daily", status.daily.resets_at, moment)
    return None


def usage_limit_message(block: UsageLimitBlock, locale: str | None = None) -> str:
    return translate(f"usage_limit.{block.reason}", locale)
