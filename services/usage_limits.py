"""利用者ごとの日次・週次の料金上限、デモアカウントの利用枠、システム全体の月予算を判定する。

Per-user daily/weekly cost limits, the demo account allowance and the system-wide monthly budget.

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
from services.usage_subject import SYSTEM_USAGE_SUBJECT, current_usage_subject, user_id_from_usage_subject

logger = logging.getLogger(__name__)

_NANO_USD_PER_USD = 1_000_000_000

LimitReason = Literal["daily", "weekly", "monthly_budget", "demo"]


@dataclass(frozen=True, slots=True)
class UsageLimitSettings:
    """設定された上限（ナノドル）。``0`` はその上限を無効にする。

    Configured limits in nano-dollars; ``0`` means the limit is disabled.
    """

    user_daily: int
    user_weekly: int
    guest_daily: int
    guest_weekly: int
    demo_total: int
    monthly_stop: int


def nano_usd_to_usd(amount: int) -> float:
    return amount / _NANO_USD_PER_USD


# 日本語: 環境変数のドル額（0 以上）をナノドルの整数にして返す。
# English: Read a dollar amount (0 or more) from the environment and return it as integer nano-dollars.
def _usd_env(name: str, default: float) -> int:
    amount = env_float(name, default, minimum=0.0, minimum_inclusive=True, warn_on_invalid=True)
    return round(amount * _NANO_USD_PER_USD)


def load_usage_limit_settings() -> UsageLimitSettings:
    """環境変数から上限を読む。毎回読み直すので、変更しても再起動やリロードが要らない。

    Read the limits from the environment on every call so changes need no reload.
    """

    ratio = min(env_float("USAGE_MONTHLY_STOP_RATIO", 0.9, warn_on_invalid=True), 1.0)
    return UsageLimitSettings(
        user_daily=_usd_env("USAGE_USER_DAILY_LIMIT_USD", 1.50),
        user_weekly=_usd_env("USAGE_USER_WEEKLY_LIMIT_USD", 6.00),
        guest_daily=_usd_env("USAGE_GUEST_DAILY_LIMIT_USD", 0.03),
        guest_weekly=_usd_env("USAGE_GUEST_WEEKLY_LIMIT_USD", 0.10),
        demo_total=_usd_env("DEMO_ACCESS_USAGE_LIMIT_USD", 1.50),
        monthly_stop=int(_usd_env("USAGE_MONTHLY_BUDGET_USD", 30.0) * ratio),
    )


@dataclass(frozen=True, slots=True)
class DemoUsageTotals:
    """デモアカウントの終了日時と、作成以降に使った料金（ナノドル）。

    A demo account's end and its cost since it was created, in nano-dollars.
    """

    expires_at: datetime
    lifetime_nano_usd: int


@dataclass(frozen=True, slots=True)
class UsageTotals:
    """上限と比べる料金（ナノドル）の集計。

    Costs in nano-dollars that the limits are compared against.
    """

    subject: SubjectUsageTotals
    monthly_total_nano_usd: int
    # デモ用アカウントのときだけ値が入る。 / Set only for a demo account.
    demo: DemoUsageTotals | None = None


@dataclass(frozen=True, slots=True)
class UsagePeriods:
    """ある時刻を含む、日本時間の暦上の日・週・月の区間。``next_*`` は各区間が切り替わる時刻（次回の利用再開時刻）。

    The Japan-time calendar windows that contain one moment.
    """

    day: date
    week_start: date
    month_start: date
    next_day: datetime
    next_week: datetime
    next_month: datetime


def usage_periods(now: datetime | None = None) -> UsagePeriods:
    """``now`` を含む日、月曜始まりの週、月を日本時間で返す。

    Return the day, the Monday-start week and the month containing ``now`` (Japan time).
    """

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


# 日本語: 計上先と期間から集計を読む関数の型。テストで差し替えられるよう、下の set_usage_totals_reader で入れ替える。
# English: Type of the function that reads totals for a subject and period; swapped through set_usage_totals_reader below, e.g. in tests.
UsageTotalsReader = Callable[[str, UsagePeriods], Awaitable[UsageTotals]]


# 日本語: DB から集計を読む既定の実装。個人の日次・週次、月の全体合計、デモ用アカウントなら全期間の合計も読む。
# English: Default reader backed by the database: personal daily/weekly totals, the monthly system total
# and, for a demo account, its lifetime total.
async def _read_usage_totals(subject_key: str, periods: UsagePeriods) -> UsageTotals:
    from services.db import session_scope
    from services.repositories.demo_access_repository import DemoAccessRepository
    from services.repositories.usage_repository import UsageRepository

    repository = UsageRepository()
    async with session_scope() as session:
        subject = await repository.subject_totals(
            session, subject_key, day=periods.day, week_start=periods.week_start
        )
        monthly = await repository.total_cost(session, start=periods.month_start, end=periods.day)
        demo = None
        user_id = user_id_from_usage_subject(subject_key)
        if user_id is not None:
            expires_at = await DemoAccessRepository(session).expiry_for_user(user_id)
            if expires_at is not None:
                # デモ用ユーザーは初回利用時に作るので、全期間の合計がデモ期間の利用額になる。
                # The demo user is created on first use, so its all-time total is the demo period's spend.
                lifetime = await repository.lifetime_costs(session, [subject_key])
                demo = DemoUsageTotals(expires_at=expires_at, lifetime_nano_usd=lifetime[subject_key])
    return UsageTotals(subject=subject, monthly_total_nano_usd=monthly, demo=demo)


_usage_totals_reader: UsageTotalsReader = _read_usage_totals


def set_usage_totals_reader(reader: UsageTotalsReader | None) -> None:
    """集計の読み取り元を差し替える。``None`` で DB 読み取りに戻す。

    Replace where totals are read from; ``None`` restores the database reader.
    """

    global _usage_totals_reader
    _usage_totals_reader = reader or _read_usage_totals


@dataclass(frozen=True, slots=True)
class UsageWindow:
    """個人の上限 1 区間（日または週）の使用量・上限・リセット時刻。

    One personal limit window.
    """

    used_nano_usd: int
    limit_nano_usd: int
    resets_at: datetime

    @property
    def exhausted(self) -> bool:
        return self.limit_nano_usd > 0 and self.used_nano_usd >= self.limit_nano_usd


@dataclass(frozen=True, slots=True)
class DemoAllowance:
    """デモアカウントの期間全体の利用枠。リセットはされず、枠を使い切るか期限が来るとアカウントが終わる。

    A demo account's allowance for its whole period; it never resets, the account just ends.
    """

    used_nano_usd: int
    limit_nano_usd: int
    expires_at: datetime

    def ended(self, now: datetime) -> bool:
        if now >= self.expires_at:
            return True
        return self.limit_nano_usd > 0 and self.used_nano_usd >= self.limit_nano_usd


@dataclass(frozen=True, slots=True)
class UsageStatus:
    """1 つの計上先が、自分の上限と月予算に対してどの位置にいるか。``daily`` / ``weekly`` が None なのは個人上限の無い system。

    Where one subject stands against its limits and the monthly budget.
    """

    daily: UsageWindow | None
    weekly: UsageWindow | None
    monthly_budget_exhausted: bool
    monthly_resets_at: datetime
    demo: DemoAllowance | None = None


@dataclass(frozen=True, slots=True)
class UsageLimitBlock:
    """新しい AI リクエストを断る理由と、再試行できる時刻・待ち秒数。

    Why a new AI request is refused and when it may be retried.
    """

    reason: LimitReason
    resets_at: datetime
    retry_after_seconds: int


# 日本語: 計上先の種類に応じた (日次, 週次) の個人上限を返す。system には個人上限が無いので None。
# English: Return the (daily, weekly) personal limits for the subject's kind; None for the system subject, which has none.
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
    """計上先（省略時は現在のリクエストの計上先）の、上限に対する現在の状況を返す。

    Return the current subject's standing against its limits.
    """

    subject_key = subject_key or current_usage_subject()
    settings = load_usage_limit_settings()
    periods = usage_periods(now)
    totals = await _usage_totals_reader(subject_key, periods)

    limits = _personal_limits(subject_key, settings)
    daily = weekly = None
    if limits is not None:
        daily = UsageWindow(totals.subject.daily_nano_usd, limits[0], periods.next_day)
        weekly = UsageWindow(totals.subject.weekly_nano_usd, limits[1], periods.next_week)
    demo = None
    if totals.demo is not None:
        demo = DemoAllowance(totals.demo.lifetime_nano_usd, settings.demo_total, totals.demo.expires_at)
    return UsageStatus(
        daily=daily,
        weekly=weekly,
        monthly_budget_exhausted=(
            settings.monthly_stop > 0 and totals.monthly_total_nano_usd >= settings.monthly_stop
        ),
        monthly_resets_at=periods.next_month,
        demo=demo,
    )


# 日本語: 制限の理由とリセット時刻から、再試行までの秒数（最低 1 秒）を計算して返す。
# English: Build a block with the seconds until reset, at least 1.
def _block(reason: LimitReason, resets_at: datetime, now: datetime) -> UsageLimitBlock:
    seconds = int((resets_at - now).total_seconds())
    return UsageLimitBlock(reason=reason, resets_at=resets_at, retry_after_seconds=max(seconds, 1))


async def check_usage_limit(
    subject_key: str | None = None,
    *,
    now: datetime | None = None,
) -> UsageLimitBlock | None:
    """新しい AI リクエストを断るべき理由を返す。開始してよければ ``None``。

    Return why a new AI request must be refused, or ``None`` when it may start.
    """

    moment = now or datetime.now(UTC)
    status = await get_usage_status(subject_key, now=moment)
    # 全体の予算が最優先。個人の枠が残っていても止める。
    # The shared budget comes first: it stops everyone, whatever their own allowance.
    if status.monthly_budget_exhausted:
        logger.warning("Monthly API budget reached; refusing new AI requests until next month.")
        return _block("monthly_budget", status.monthly_resets_at, moment)
    # デモ用アカウントの枠は期間中に戻らない。期限を過ぎて削除を待つ間もここで止める。
    # A demo allowance never comes back within its period; this also stops an expired account
    # that the periodic purge has not deleted yet.
    if status.demo is not None and status.demo.ended(moment):
        return _block("demo", status.demo.expires_at, moment)
    # 週の枠が尽きていれば、日が変わっても使えないので週の方を案内する。
    # When the weekly allowance is gone a new day does not help, so report the week.
    if status.weekly is not None and status.weekly.exhausted:
        return _block("weekly", status.weekly.resets_at, moment)
    if status.daily is not None and status.daily.exhausted:
        return _block("daily", status.daily.resets_at, moment)
    return None


# 日本語: 制限の理由に対応する、利用者向けの翻訳済みメッセージを返す。
# English: Return the translated user-facing message for the limit reason.
def usage_limit_message(block: UsageLimitBlock, locale: str | None = None) -> str:
    return translate(f"usage_limit.{block.reason}", locale)
