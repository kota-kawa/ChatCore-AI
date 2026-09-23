"""Meter API usage and store it as a cost per billing subject and day.

プロバイダ呼び出しの直後に呼ばれ、トークン数を料金に換算して、現在の計上先
（`services.usage_subject`）の当日分へ加算します。DB への書き込みは応答経路を
遅らせないようバックグラウンドで行い、失敗しても呼び出し元へは伝えません。
Called right after each provider call: it converts tokens into a cost and adds it to the
current billing subject's total for the day. The database write runs in the background
so it never delays a response, and a failed write is logged rather than raised.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone

from services.repositories.usage_repository import UsageIncrement
from services.usage_pricing import BRAVE_WEB_SEARCH_REQUEST_NANO_USD, token_cost_nano_usd
from services.usage_subject import current_usage_subject

logger = logging.getLogger(__name__)

# 日・週の区切りは日本時間で数える。日本時間に夏時間は無いため固定オフセットで足りる。
# Days and weeks are counted in Japan time, which has no daylight saving, so a fixed
# offset is exact.
USAGE_TIMEZONE = timezone(timedelta(hours=9), name="JST")

BRAVE_WEB_SEARCH_RESOURCE = "brave_web_search"

UsageSink = Callable[[UsageIncrement], None]


def usage_date(now: datetime | None = None) -> date:
    """Return the billing day (Japan time) for ``now``."""

    moment = now or datetime.now(UTC)
    return moment.astimezone(USAGE_TIMEZONE).date()


async def _persist_usage(increment: UsageIncrement) -> None:
    # DB 層の import を遅らせ、LLM モジュールを読むだけで DB 設定を要求しないようにする。
    # Import the database layer lazily so importing the LLM module never needs DB settings.
    from services.db import session_scope
    from services.repositories.usage_repository import UsageRepository

    async with session_scope() as session:
        await UsageRepository().add_usage(session, increment)
        await session.commit()


def _run_persist_usage(increment: UsageIncrement) -> None:
    from services.chat_async_bridge import _run_async_callback

    try:
        _run_async_callback(lambda: _persist_usage(increment))
    except Exception:
        logger.exception(
            "Failed to record API usage (subject=%s, resource=%s, cost_nano_usd=%s).",
            increment.subject_key,
            increment.resource,
            increment.cost_nano_usd,
        )


def _persist_in_background(increment: UsageIncrement) -> None:
    from services.background_executor import submit_background_task

    try:
        submit_background_task(_run_persist_usage, increment)
    except Exception:
        # 終了処理中などで投入できない場合は、その場で書く。取りこぼすと上限が甘くなる。
        # When the executor refuses work (for example during shutdown), write inline:
        # dropping the record would make the limits more permissive.
        _run_persist_usage(increment)


_usage_sink: UsageSink = _persist_in_background


def set_usage_sink(sink: UsageSink | None) -> None:
    """Replace where usage records go; ``None`` restores the database writer."""

    global _usage_sink
    _usage_sink = sink or _persist_in_background


def _emit(increment: UsageIncrement) -> None:
    try:
        _usage_sink(increment)
    except Exception:
        logger.exception("Failed to hand off an API usage record.")


def record_token_usage(
    resource: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> None:
    """Record one model call for the current billing subject."""

    input_tokens = max(int(input_tokens or 0), 0)
    output_tokens = max(int(output_tokens or 0), 0)
    cached_input_tokens = min(max(int(cached_input_tokens or 0), 0), input_tokens)
    _emit(
        UsageIncrement(
            subject_key=current_usage_subject(),
            usage_date=usage_date(),
            resource=resource,
            cost_nano_usd=token_cost_nano_usd(
                resource,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
            ),
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
        )
    )


def record_web_search_request() -> None:
    """Record one paid web search request for the current billing subject."""

    _emit(
        UsageIncrement(
            subject_key=current_usage_subject(),
            usage_date=usage_date(),
            resource=BRAVE_WEB_SEARCH_RESOURCE,
            cost_nano_usd=BRAVE_WEB_SEARCH_REQUEST_NANO_USD,
        )
    )
