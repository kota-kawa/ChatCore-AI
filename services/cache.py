import logging
import os
import queue
import threading
import time
from typing import Any

try:
    import redis
except ModuleNotFoundError:  # pragma: no cover - optional for test envs
    redis = None


_redis_client: Any | None = None
_redis_retry_after = 0.0

DEFAULT_REDIS_RETRY_COOLDOWN_SECONDS = 5
DEFAULT_REDIS_CONNECT_TIMEOUT_SECONDS = 1.0

logger = logging.getLogger(__name__)


# 日本語: is redis configured に関する処理の入口です。
# English: Entry point for logic related to is redis configured.
def is_redis_configured() -> bool:
    return bool(os.environ.get("REDIS_URL") or os.environ.get("REDIS_HOST"))


# 日本語: get positive float env の取得処理を担当します。
# English: Handle fetching for get positive float env.
def _get_positive_float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if raw_value is None:
        return default
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# 日本語: mark redis unavailable に関する処理の入口です。
# English: Entry point for logic related to mark redis unavailable.
def mark_redis_unavailable(exc: Exception | None = None) -> None:
    global _redis_client, _redis_retry_after
    _redis_client = None
    _redis_retry_after = time.monotonic() + DEFAULT_REDIS_RETRY_COOLDOWN_SECONDS
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if exc is not None:
        logger.warning(
            "Redis is unavailable; falling back to local session/cache behavior for %s seconds.",
            DEFAULT_REDIS_RETRY_COOLDOWN_SECONDS,
            extra={"error_class": exc.__class__.__name__},
        )


# 日本語: ping redis with timeout に関する処理の入口です。
# English: Entry point for logic related to ping redis with timeout.
def _ping_redis_with_timeout(candidate: Any, timeout_seconds: float) -> None:
    result_queue: queue.Queue[Exception | None] = queue.Queue(maxsize=1)

    # 日本語: ping に関する処理の入口です。
    # English: Entry point for logic related to ping.
    def ping() -> None:
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            candidate.ping()
        except Exception as exc:
            result_queue.put(exc)
            return
        result_queue.put(None)

    thread = threading.Thread(target=ping, daemon=True)
    thread.start()
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        exc = result_queue.get(timeout=timeout_seconds)
    except queue.Empty as exc:
        raise TimeoutError("Timed out while connecting to Redis.") from exc
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if exc is not None:
        raise exc


# 日本語: get redis client の取得処理を担当します。
# English: Handle fetching for get redis client.
def get_redis_client() -> Any | None:
    # Redis 依存がない環境では None を返し、呼び出し側がメモリ実装へフォールバックする
    # Return None when Redis dependency is unavailable so callers can fallback to memory.
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if redis is None:
        return None
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not is_redis_configured():
        return None

    global _redis_client, _redis_retry_after
    if _redis_client is not None:
        return _redis_client
    if time.monotonic() < _redis_retry_after:
        return None

    # URL 指定を最優先し、未指定時は host/port/db 設定で接続する
    # Prefer REDIS_URL, otherwise build client from host/port/db settings.
    url = os.environ.get("REDIS_URL")
    connect_timeout = _get_positive_float_env(
        "REDIS_CONNECT_TIMEOUT_SECONDS",
        DEFAULT_REDIS_CONNECT_TIMEOUT_SECONDS,
    )

    if url:
        candidate = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=connect_timeout,
            socket_timeout=connect_timeout,
        )
    else:
        host = os.environ.get("REDIS_HOST")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        db = int(os.environ.get("REDIS_DB", "0"))
        password = os.environ.get("REDIS_PASSWORD")
        candidate = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
            socket_connect_timeout=connect_timeout,
            socket_timeout=connect_timeout,
        )

    try:
        _ping_redis_with_timeout(candidate, connect_timeout)
    except Exception as exc:
        mark_redis_unavailable(exc)
        return None

    _redis_retry_after = 0.0
    _redis_client = candidate
    return _redis_client
