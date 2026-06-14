import hashlib
import logging
import os
from collections.abc import Callable
from datetime import date, datetime, timedelta
from threading import Lock
from typing import Any

from fastapi import Request

from services.cache import get_redis_client


DEFAULT_LLM_DAILY_API_LIMIT = 300
LLM_DAILY_API_LIMIT_ENV = "LLM_DAILY_API_LIMIT"
_LLM_DAILY_COUNT_KEY_PREFIX = "llm:daily_api_total"

DEFAULT_AUTH_EMAIL_DAILY_SEND_LIMIT = 50
AUTH_EMAIL_DAILY_SEND_LIMIT_ENV = "AUTH_EMAIL_DAILY_SEND_LIMIT"
_AUTH_EMAIL_DAILY_COUNT_KEY_PREFIX = "auth_email:daily_send_total"

DEFAULT_AI_AGENT_MONTHLY_API_LIMIT = 1000
AI_AGENT_MONTHLY_API_LIMIT_ENV = "AI_AGENT_MONTHLY_API_LIMIT"
_AI_AGENT_MONTHLY_COUNT_KEY_PREFIX = "llm:agent_monthly_total"

DEFAULT_BRAVE_WEB_SEARCH_MONTHLY_LIMIT = 500
BRAVE_WEB_SEARCH_MONTHLY_LIMIT_ENV = "BRAVE_WEB_SEARCH_MONTHLY_LIMIT"
_BRAVE_WEB_SEARCH_MONTHLY_COUNT_KEY_PREFIX = "brave:web_search_monthly_total"

logger = logging.getLogger(__name__)


# 日本語: get limit の取得処理を担当します。
# English: Handle fetching for get limit.
def _get_limit(env_name: str, default_limit: int) -> int:
    # 環境変数値を整数化し、異常値はデフォルトへフォールバックする
    # Parse limit from env and fallback to default on invalid values.
    raw_limit = os.environ.get(env_name, str(default_limit))
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid %s value '%s'. Falling back to %s.",
            env_name,
            raw_limit,
            default_limit,
        )
        return default_limit
    return max(limit, 0)


# 日本語: seconds until tomorrow に関する処理の入口です。
# English: Entry point for logic related to seconds until tomorrow.
def _seconds_until_tomorrow() -> int:
    # 日次クォータのキー期限を「次の0時」までに合わせる
    # Compute TTL that expires at the next midnight.
    now = datetime.now()
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    seconds = int((tomorrow - now).total_seconds())
    return max(seconds, 1)


# 日本語: seconds until next month に関する処理の入口です。
# English: Entry point for logic related to seconds until next month.
def _seconds_until_next_month() -> int:
    # 月次クォータのキー期限を「翌月1日の0時」までに合わせる
    # Compute TTL that expires at the first day of the next month.
    now = datetime.now()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if now.month == 12:
        first_of_next_month = datetime(now.year + 1, 1, 1)
    else:
        first_of_next_month = datetime(now.year, now.month + 1, 1)
    seconds = int((first_of_next_month - now).total_seconds())
    return max(seconds, 1)


# 日本語: get seconds until daily reset の取得処理を担当します。
# English: Handle fetching for get seconds until daily reset.
def get_seconds_until_daily_reset() -> int:
    return _seconds_until_tomorrow()


# 日本語: get seconds until monthly reset の取得処理を担当します。
# English: Handle fetching for get seconds until monthly reset.
def get_seconds_until_monthly_reset() -> int:
    return _seconds_until_next_month()


# 日本語: LlmDailyLimitService に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to LlmDailyLimitService.
class LlmDailyLimitService:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(
        self,
        *,
        redis_client_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self._redis_client_getter = redis_client_getter
        self._in_memory_lock = Lock()
        self._in_memory_daily_counts: dict[str, int] = {}
        self._in_memory_monthly_counts: dict[str, int] = {}

    # 日本語: get redis client の取得処理を担当します。
    # English: Handle fetching for get redis client.
    def _get_redis_client(self) -> Any | None:
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self._redis_client_getter is not None:
            return self._redis_client_getter()
        return get_redis_client()

    # 日本語: reset in memory state に関する処理の入口です。
    # English: Entry point for logic related to reset in memory state.
    def reset_in_memory_state(self) -> None:
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._in_memory_lock:
            self._in_memory_daily_counts.clear()
            self._in_memory_monthly_counts.clear()

    # 日本語: consume with redis に関する処理の入口です。
    # English: Entry point for logic related to consume with redis.
    def _consume_with_redis(
        self,
        redis_client: Any,
        redis_key: str,
        limit: int,
        ttl_seconds: int,
    ) -> tuple[bool, int] | None:
        # Redis Lua で INCR+EXPIRE を原子的に実行し、競合時の取りこぼしを防ぐ
        # Use Redis Lua for atomic INCR+EXPIRE to avoid race conditions.
        lua_script = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = tonumber(redis.call('GET', key) or '0')

if current >= limit then
  return {0, current}
end

current = redis.call('INCR', key)
if current == 1 then
  redis.call('EXPIRE', key, ttl)
end

return {1, current}
"""
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            result = redis_client.eval(
                lua_script,
                1,
                redis_key,
                limit,
                ttl_seconds,
            )
            if not isinstance(result, (list, tuple)) or len(result) != 2:
                raise ValueError(f"Unexpected Redis result: {result}")
            allowed = int(result[0]) == 1
            current = int(result[1])
            remaining = max(limit - current, 0)
            return allowed, remaining
        except Exception:
            logger.exception("Redis quota tracking failed; falling back to in-memory.")
            return None

    # 日本語: consume with in memory に関する処理の入口です。
    # English: Entry point for logic related to consume with in memory.
    def _consume_with_in_memory(
        self,
        counts: dict[str, int],
        quota_key: str,
        current_period: str,
        limit: int,
    ) -> tuple[bool, int]:
        # Redis 不可時のフォールバック。期間が変わったキーを都度掃除する
        # Fallback path when Redis is unavailable; prune stale period keys on each call.
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._in_memory_lock:
            period_suffix = f":{current_period}"
            stale_keys = [
                key for key in counts if not key.endswith(period_suffix)
            ]
            for key in stale_keys:
                counts.pop(key, None)

            current = counts.get(quota_key, 0)
            if current >= limit:
                return False, 0

            current += 1
            counts[quota_key] = current
            remaining = max(limit - current, 0)
            return True, remaining

    # 日本語: consume daily quota に関する処理の入口です。
    # English: Entry point for logic related to consume daily quota.
    def _consume_daily_quota(
        self,
        *,
        key_prefix: str,
        env_name: str,
        default_limit: int,
        current_date: str | None = None,
        user_key: str | None = None,
    ) -> tuple[bool, int, int]:
        # 1日単位キーを作って Redis 優先で消費し、失敗時のみメモリ実装へ切り替える
        # Consume quota using a day-scoped key, preferring Redis and falling back to memory.
        # When user_key is provided the quota is scoped per user/session so one
        # caller cannot burn the global daily budget for everyone else.
        daily_limit = _get_limit(env_name, default_limit)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if daily_limit <= 0:
            return False, 0, daily_limit

        today = current_date or date.today().isoformat()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if user_key:
            # Hash to avoid leaking user identifiers into Redis keys and to
            # keep key length bounded regardless of input.
            hashed = hashlib.sha256(user_key.encode("utf-8", errors="replace")).hexdigest()
            quota_key = f"{key_prefix}:user:{hashed}:{today}"
        else:
            quota_key = f"{key_prefix}:{today}"

        redis_client = self._get_redis_client()
        if redis_client is not None:
            redis_result = self._consume_with_redis(
                redis_client,
                quota_key,
                daily_limit,
                _seconds_until_tomorrow(),
            )
            if redis_result is not None:
                allowed, remaining = redis_result
                return allowed, remaining, daily_limit

        allowed, remaining = self._consume_with_in_memory(
            self._in_memory_daily_counts,
            quota_key,
            today,
            daily_limit,
        )
        return allowed, remaining, daily_limit

    # 日本語: consume monthly quota に関する処理の入口です。
    # English: Entry point for logic related to consume monthly quota.
    def _consume_monthly_quota(
        self,
        *,
        key_prefix: str,
        env_name: str,
        default_limit: int,
        current_month: str | None = None,
    ) -> tuple[bool, int, int]:
        # 月単位キーを作って Redis 優先で消費し、失敗時のみメモリ実装へ切り替える
        # Consume quota using a month-scoped key, preferring Redis and falling back to memory.
        monthly_limit = _get_limit(env_name, default_limit)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if monthly_limit <= 0:
            return False, 0, monthly_limit

        month = current_month or date.today().strftime("%Y-%m")
        quota_key = f"{key_prefix}:{month}"

        redis_client = self._get_redis_client()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is not None:
            redis_result = self._consume_with_redis(
                redis_client,
                quota_key,
                monthly_limit,
                _seconds_until_next_month(),
            )
            if redis_result is not None:
                allowed, remaining = redis_result
                return allowed, remaining, monthly_limit

        allowed, remaining = self._consume_with_in_memory(
            self._in_memory_monthly_counts,
            quota_key,
            month,
            monthly_limit,
        )
        return allowed, remaining, monthly_limit

    # 日本語: consume llm daily quota に関する処理の入口です。
    # English: Entry point for logic related to consume llm daily quota.
    def consume_llm_daily_quota(
        self,
        current_date: str | None = None,
        *,
        user_key: str | None = None,
    ) -> tuple[bool, int, int]:
        # チャット応答 API 用の日次上限を 1 回分消費する
        # Consume one unit from the daily quota for chat API usage. The quota
        # is scoped per user_key so a single account can't deny service to
        # everyone else by burning the global daily budget.
        return self._consume_daily_quota(
            key_prefix=_LLM_DAILY_COUNT_KEY_PREFIX,
            env_name=LLM_DAILY_API_LIMIT_ENV,
            default_limit=DEFAULT_LLM_DAILY_API_LIMIT,
            current_date=current_date,
            user_key=user_key,
        )

    # 日本語: consume auth email daily quota に関する処理の入口です。
    # English: Entry point for logic related to consume auth email daily quota.
    def consume_auth_email_daily_quota(
        self,
        current_date: str | None = None,
    ) -> tuple[bool, int, int]:
        # 認証メール送信用の日次上限を 1 回分消費する
        # Consume one unit from the daily quota for auth email sending.
        return self._consume_daily_quota(
            key_prefix=_AUTH_EMAIL_DAILY_COUNT_KEY_PREFIX,
            env_name=AUTH_EMAIL_DAILY_SEND_LIMIT_ENV,
            default_limit=DEFAULT_AUTH_EMAIL_DAILY_SEND_LIMIT,
            current_date=current_date,
        )

    # 日本語: consume ai agent monthly quota に関する処理の入口です。
    # English: Entry point for logic related to consume ai agent monthly quota.
    def consume_ai_agent_monthly_quota(
        self,
        current_month: str | None = None,
    ) -> tuple[bool, int, int]:
        # サポートAIエージェント用の月次上限を 1 回分消費する
        # Consume one unit from the monthly quota for support AI agent usage.
        return self._consume_monthly_quota(
            key_prefix=_AI_AGENT_MONTHLY_COUNT_KEY_PREFIX,
            env_name=AI_AGENT_MONTHLY_API_LIMIT_ENV,
            default_limit=DEFAULT_AI_AGENT_MONTHLY_API_LIMIT,
            current_month=current_month,
        )

    # 日本語: consume brave web search monthly quota に関する処理の入口です。
    # English: Entry point for logic related to consume brave web search monthly quota.
    def consume_brave_web_search_monthly_quota(
        self,
        current_month: str | None = None,
    ) -> tuple[bool, int, int]:
        # Brave Web検索用の全体月次上限を 1 回分消費する
        # Consume one unit from the global monthly quota for Brave web search usage.
        return self._consume_monthly_quota(
            key_prefix=_BRAVE_WEB_SEARCH_MONTHLY_COUNT_KEY_PREFIX,
            env_name=BRAVE_WEB_SEARCH_MONTHLY_LIMIT_ENV,
            default_limit=DEFAULT_BRAVE_WEB_SEARCH_MONTHLY_LIMIT,
            current_month=current_month,
        )


# 日本語: get llm daily api limit の取得処理を担当します。
# English: Handle fetching for get llm daily api limit.
def get_llm_daily_api_limit() -> int:
    return _get_limit(LLM_DAILY_API_LIMIT_ENV, DEFAULT_LLM_DAILY_API_LIMIT)


# 日本語: get auth email daily send limit の取得処理を担当します。
# English: Handle fetching for get auth email daily send limit.
def get_auth_email_daily_send_limit() -> int:
    return _get_limit(
        AUTH_EMAIL_DAILY_SEND_LIMIT_ENV, DEFAULT_AUTH_EMAIL_DAILY_SEND_LIMIT
    )


# 日本語: get ai agent monthly api limit の取得処理を担当します。
# English: Handle fetching for get ai agent monthly api limit.
def get_ai_agent_monthly_api_limit() -> int:
    return _get_limit(
        AI_AGENT_MONTHLY_API_LIMIT_ENV,
        DEFAULT_AI_AGENT_MONTHLY_API_LIMIT,
    )


# 日本語: get brave web search monthly limit の取得処理を担当します。
# English: Handle fetching for get brave web search monthly limit.
def get_brave_web_search_monthly_limit() -> int:
    return _get_limit(
        BRAVE_WEB_SEARCH_MONTHLY_LIMIT_ENV,
        DEFAULT_BRAVE_WEB_SEARCH_MONTHLY_LIMIT,
    )


_default_llm_daily_limit_service = LlmDailyLimitService()


# 日本語: get llm daily limit service の取得処理を担当します。
# English: Handle fetching for get llm daily limit service.
def get_llm_daily_limit_service(request: Request = None) -> LlmDailyLimitService:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if request is not None:
        app = request.scope.get("app")
        state = getattr(app, "state", None)
        service = getattr(state, "llm_daily_limit_service", None)
        if isinstance(service, LlmDailyLimitService):
            return service
    return _default_llm_daily_limit_service


# 日本語: clear in memory daily limit state の初期化処理を担当します。
# English: Handle clearing for clear in memory daily limit state.
def clear_in_memory_daily_limit_state() -> None:
    get_llm_daily_limit_service().reset_in_memory_state()


# 日本語: consume llm daily quota に関する処理の入口です。
# English: Entry point for logic related to consume llm daily quota.
def consume_llm_daily_quota(
    current_date: str | None = None,
    *,
    service: LlmDailyLimitService | None = None,
    user_key: str | None = None,
) -> tuple[bool, int, int]:
    target = (
        service
        if isinstance(service, LlmDailyLimitService)
        else get_llm_daily_limit_service()
    )
    return target.consume_llm_daily_quota(current_date=current_date, user_key=user_key)


# 日本語: consume auth email daily quota に関する処理の入口です。
# English: Entry point for logic related to consume auth email daily quota.
def consume_auth_email_daily_quota(
    current_date: str | None = None,
    *,
    service: LlmDailyLimitService | None = None,
) -> tuple[bool, int, int]:
    target = (
        service
        if isinstance(service, LlmDailyLimitService)
        else get_llm_daily_limit_service()
    )
    return target.consume_auth_email_daily_quota(
        current_date=current_date
    )


# 日本語: consume ai agent monthly quota に関する処理の入口です。
# English: Entry point for logic related to consume ai agent monthly quota.
def consume_ai_agent_monthly_quota(
    current_month: str | None = None,
    *,
    service: LlmDailyLimitService | None = None,
) -> tuple[bool, int, int]:
    target = (
        service
        if isinstance(service, LlmDailyLimitService)
        else get_llm_daily_limit_service()
    )
    return target.consume_ai_agent_monthly_quota(current_month=current_month)


# 日本語: consume brave web search monthly quota に関する処理の入口です。
# English: Entry point for logic related to consume brave web search monthly quota.
def consume_brave_web_search_monthly_quota(
    current_month: str | None = None,
    *,
    service: LlmDailyLimitService | None = None,
) -> tuple[bool, int, int]:
    target = (
        service
        if isinstance(service, LlmDailyLimitService)
        else get_llm_daily_limit_service()
    )
    return target.consume_brave_web_search_monthly_quota(current_month=current_month)
