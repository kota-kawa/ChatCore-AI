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

logger = logging.getLogger(__name__)


def _get_daily_limit(env_name: str, default_limit: int) -> int:
    # 環境変数値を整数化し、異常値はデフォルトへフォールバックする
    # Parse daily limit from env and fallback to default on invalid values.
    raw_limit = os.environ.get(env_name, str(default_limit))
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


def _seconds_until_tomorrow() -> int:
    # 日次クォータのキー期限を「次の0時」までに合わせる
    # Compute TTL that expires at the next midnight.
    now = datetime.now()
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    seconds = int((tomorrow - now).total_seconds())
    return max(seconds, 1)


def get_seconds_until_daily_reset() -> int:
    return _seconds_until_tomorrow()


class LlmDailyLimitService:
    def __init__(
        self,
        *,
        redis_client_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self._redis_client_getter = redis_client_getter
        self._in_memory_lock = Lock()
        self._in_memory_daily_counts: dict[str, int] = {}

    def _get_redis_client(self) -> Any | None:
        if self._redis_client_getter is not None:
            return self._redis_client_getter()
        return get_redis_client()

    def reset_in_memory_state(self) -> None:
        with self._in_memory_lock:
            self._in_memory_daily_counts.clear()

    def _consume_with_redis(
        self, redis_client: Any, redis_key: str, daily_limit: int
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
        try:
            result = redis_client.eval(
                lua_script,
                1,
                redis_key,
                daily_limit,
                _seconds_until_tomorrow(),
            )
            if not isinstance(result, (list, tuple)) or len(result) != 2:
                raise ValueError(f"Unexpected Redis result: {result}")
            allowed = int(result[0]) == 1
            current = int(result[1])
            remaining = max(daily_limit - current, 0)
            return allowed, remaining
        except Exception:
            logger.exception("Redis quota tracking failed; falling back to in-memory.")
            return None

    def _consume_with_in_memory(
        self, daily_key: str, current_date: str, daily_limit: int
    ) -> tuple[bool, int]:
        # Redis 不可時のフォールバック。日付が変わったキーを都度掃除する
        # Fallback path when Redis is unavailable; prune stale day keys on each call.
        with self._in_memory_lock:
            date_suffix = f":{current_date}"
            stale_keys = [
                key for key in self._in_memory_daily_counts if not key.endswith(date_suffix)
            ]
            for key in stale_keys:
                self._in_memory_daily_counts.pop(key, None)

            current = self._in_memory_daily_counts.get(daily_key, 0)
            if current >= daily_limit:
                return False, 0

            current += 1
            self._in_memory_daily_counts[daily_key] = current
            remaining = max(daily_limit - current, 0)
            return True, remaining

    def _consume_daily_quota(
        self,
        *,
        key_prefix: str,
        env_name: str,
        default_limit: int,
        current_date: str | None = None,
    ) -> tuple[bool, int, int]:
        # 1日単位キーを作って Redis 優先で消費し、失敗時のみメモリ実装へ切り替える
        # Consume quota using a day-scoped key, preferring Redis and falling back to memory.
        daily_limit = _get_daily_limit(env_name, default_limit)
        if daily_limit <= 0:
            return False, 0, daily_limit

        today = current_date or date.today().isoformat()
        quota_key = f"{key_prefix}:{today}"

        redis_client = self._get_redis_client()
        if redis_client is not None:
            redis_result = self._consume_with_redis(redis_client, quota_key, daily_limit)
            if redis_result is not None:
                allowed, remaining = redis_result
                return allowed, remaining, daily_limit

        allowed, remaining = self._consume_with_in_memory(quota_key, today, daily_limit)
        return allowed, remaining, daily_limit

    def consume_llm_daily_quota(self, current_date: str | None = None) -> tuple[bool, int, int]:
        # チャット応答 API 用の日次上限を 1 回分消費する
        # Consume one unit from the daily quota for chat API usage.
        return self._consume_daily_quota(
            key_prefix=_LLM_DAILY_COUNT_KEY_PREFIX,
            env_name=LLM_DAILY_API_LIMIT_ENV,
            default_limit=DEFAULT_LLM_DAILY_API_LIMIT,
            current_date=current_date,
        )

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


def get_llm_daily_api_limit() -> int:
    return _get_daily_limit(LLM_DAILY_API_LIMIT_ENV, DEFAULT_LLM_DAILY_API_LIMIT)


def get_auth_email_daily_send_limit() -> int:
    return _get_daily_limit(
        AUTH_EMAIL_DAILY_SEND_LIMIT_ENV, DEFAULT_AUTH_EMAIL_DAILY_SEND_LIMIT
    )


_default_llm_daily_limit_service = LlmDailyLimitService()


def get_llm_daily_limit_service(request: Request = None) -> LlmDailyLimitService:
    if request is not None:
        app = request.scope.get("app")
        state = getattr(app, "state", None)
        service = getattr(state, "llm_daily_limit_service", None)
        if isinstance(service, LlmDailyLimitService):
            return service
    return _default_llm_daily_limit_service


def clear_in_memory_daily_limit_state() -> None:
    get_llm_daily_limit_service().reset_in_memory_state()


def consume_llm_daily_quota(
    current_date: str | None = None,
    *,
    service: LlmDailyLimitService | None = None,
) -> tuple[bool, int, int]:
    target = (
        service
        if isinstance(service, LlmDailyLimitService)
        else get_llm_daily_limit_service()
    )
    return target.consume_llm_daily_quota(current_date=current_date)


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
