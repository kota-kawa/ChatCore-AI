"""API の使用量を計測し、計上先ごと・日ごとの料金として保存する。

Meter API usage and store it as a cost per billing subject and day.

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
    """``now`` に対応する計上日（日本時間）を返す。

    Return the billing day (Japan time) for ``now``.
    """

    moment = now or datetime.now(UTC)
    return moment.astimezone(USAGE_TIMEZONE).date()


# 日本語: 使用量 1 件を DB に加算して確定する。
# English: Add one usage record to the database and commit.
async def _persist_usage(increment: UsageIncrement) -> None:
    # DB 層の import を遅らせ、LLM モジュールを読むだけで DB 設定を要求しないようにする。
    # Import the database layer lazily so importing the LLM module never needs DB settings.
    from services.db import session_scope
    from services.repositories.usage_repository import UsageRepository

    async with session_scope() as session:
        await UsageRepository().add_usage(session, increment)
        await session.commit()


# 日本語: 非同期の保存を同期スレッドから実行する。失敗は握りつぶさずログに残し、呼び出し元へは伝えない。
# English: Run the async save from a synchronous thread; a failure is logged and never propagated to the caller.
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


# 日本語: 保存をバックグラウンドの実行基盤に投入する。応答経路を遅らせないための既定の出力先。
# English: Hand the save to the background executor; the default sink, so responses are never delayed.
def _persist_in_background(increment: UsageIncrement) -> None:
    from services.background_executor import submit_background_task

    try:
        submit_background_task(_run_persist_usage, increment)
    except Exception:
        # 終了処理中などで投入できない場合は、その場で書く。取りこぼすと上限が甘くなる。
        # When the executor refuses work (for example during shutdown), write inline:
        # dropping the record would make the limits more permissive.
        _run_persist_usage(increment)


# 日本語: 使用量の出力先。通常は DB 保存で、テストでは set_usage_sink で差し替える。
# English: Where usage records go: the database writer normally, replaceable through set_usage_sink in tests.
_usage_sink: UsageSink = _persist_in_background


def set_usage_sink(sink: UsageSink | None) -> None:
    """使用量の出力先を差し替える。``None`` で DB への書き込みに戻す。

    Replace where usage records go; ``None`` restores the database writer.
    """

    global _usage_sink
    _usage_sink = sink or _persist_in_background


# 日本語: 出力先へ渡す。渡すこと自体が失敗しても呼び出し元（LLM 応答）には影響させず、ログだけ残す。
# English: Pass the record to the sink; even if the hand-off fails the caller (the LLM response) is unaffected and only a log is written.
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
    cache_write_input_tokens: int = 0,
) -> None:
    """現在の計上先について、モデル呼び出し 1 回分を記録する。

    トークン数は 0 以上に丸め、キャッシュ読み取り・書き込みの合計が入力トークン数を超えないようにする。

    Record one model call for the current billing subject.

    Token counts are clamped at zero and the cached and cache-write portions never exceed the input total.
    """

    input_tokens = max(int(input_tokens or 0), 0)
    output_tokens = max(int(output_tokens or 0), 0)
    cached_input_tokens = min(max(int(cached_input_tokens or 0), 0), input_tokens)
    cache_write_input_tokens = min(
        max(int(cache_write_input_tokens or 0), 0), input_tokens - cached_input_tokens
    )
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
                cache_write_input_tokens=cache_write_input_tokens,
            ),
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
        )
    )


def record_web_search_request() -> None:
    """現在の計上先について、有料の Web 検索リクエスト 1 回分を記録する。

    Record one paid web search request for the current billing subject.
    """

    _emit(
        UsageIncrement(
            subject_key=current_usage_subject(),
            usage_date=usage_date(),
            resource=BRAVE_WEB_SEARCH_RESOURCE,
            cost_nano_usd=BRAVE_WEB_SEARCH_REQUEST_NANO_USD,
        )
    )
