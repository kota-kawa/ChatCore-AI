import json
import logging
import os
import queue
import threading
import time
import uuid
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


# 環境変数にRedis設定（URLまたはHOST）が存在するか判定する
# Check if Redis configuration (URL or HOST) exists in environment variables
def is_redis_configured() -> bool:
    return bool(os.environ.get("REDIS_URL") or os.environ.get("REDIS_HOST"))


# 環境変数から正の浮動小数点数値を取得するヘルパー関数
# Helper function to get a positive float from environment variables
def _get_positive_float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# Redisへの接続が失敗した際に、一時的にRedis利用を無効化する
# Temporarily disable Redis usage when connection fails
def mark_redis_unavailable(exc: Exception | None = None) -> None:
    global _redis_client, _redis_retry_after
    _redis_client = None
    # 次の再試行可能時刻をクールダウン秒数後に設定する
    # Set the next retry timestamp after the cooldown duration
    _redis_retry_after = time.monotonic() + DEFAULT_REDIS_RETRY_COOLDOWN_SECONDS
    if exc is not None:
        logger.warning(
            "Redis is unavailable; falling back to local session/cache behavior for %s seconds.",
            DEFAULT_REDIS_RETRY_COOLDOWN_SECONDS,
            extra={"error_class": exc.__class__.__name__},
        )


# Redisに対するping疎通確認をタイムアウト付きで実行する
# Execute ping check to Redis with a timeout duration
def _ping_redis_with_timeout(candidate: Any, timeout_seconds: float) -> None:
    result_queue: queue.Queue[Exception | None] = queue.Queue(maxsize=1)

    # 別スレッドでpingを実行してキュー経由で結果を返す関数
    # Internal function to run ping in a separate thread and return result via queue
    def ping() -> None:
        try:
            candidate.ping()
        except Exception as exc:
            result_queue.put(exc)
            return
        result_queue.put(None)

    thread = threading.Thread(target=ping, daemon=True)
    thread.start()
    try:
        # タイムアウト付きでキューから結果を取得
        # Retrieve the result from the queue with a timeout
        exc = result_queue.get(timeout=timeout_seconds)
    except queue.Empty as exc:
        raise TimeoutError("Timed out while connecting to Redis.") from exc
    if exc is not None:
        raise exc


# Redisクライアントインスタンスを取得する
# Retrieve the Redis client instance
def get_redis_client() -> Any | None:
    # Redis 依存がない環境では None を返し、呼び出し側がメモリ実装へフォールバックする
    # Return None when Redis dependency is unavailable so callers can fallback to memory.
    if redis is None:
        return None
    if not is_redis_configured():
        return None

    global _redis_client, _redis_retry_after
    if _redis_client is not None:
        return _redis_client
    # 前回の失敗からクールダウン期間が明けているか確認
    # Check if the cooldown period has elapsed since the last failure
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

    # 接続確認pingを実行する
    # Execute a connection verification ping
    try:
        _ping_redis_with_timeout(candidate, connect_timeout)
    except Exception as exc:
        mark_redis_unavailable(exc)
        return None

    _redis_retry_after = 0.0
    _redis_client = candidate
    return _redis_client


# 複数ワーカー間で「一度きり実行」を保証するための分散ロックを取得する。
# Redis 未設定・接続不可の場合は True を返し、単一プロセス前提の処理を妨げない。
# Acquire a best-effort distributed single-flight lock so only one worker runs a job per window.
# Returns True when Redis is unavailable so single-process deployments still proceed.
def try_acquire_single_flight(name: str, ttl_seconds: int) -> bool:
    client = get_redis_client()
    if client is None:
        return True
    try:
        # SET key value NX EX ttl: 最初に獲得したワーカーのみ True を得る
        # SET ... NX EX grants the lock to whichever worker writes the key first.
        acquired = client.set(
            f"single_flight:{name}",
            uuid.uuid4().hex,
            nx=True,
            ex=max(int(ttl_seconds), 1),
        )
        return bool(acquired)
    except Exception as exc:
        # ロック調整に失敗したらフェイルオープン（実行する側に倒す）
        # Fail open on coordination errors so the work is not silently skipped.
        mark_redis_unavailable(exc)
        return True


# キャッシュから JSON 値を取得する。未ヒット・障害時は None を返す。
# Read a JSON-encoded value from the cache. Returns None on miss or any failure.
def cache_get_json(key: str) -> Any | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception as exc:
        mark_redis_unavailable(exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


# JSON シリアライズ可能な値を TTL 付きでキャッシュへ書き込む。障害時は黙って諦める。
# Write a JSON-serializable value with a TTL. Silently gives up on any failure.
def cache_set_json(key: str, value: Any, ttl_seconds: int) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return
    try:
        client.set(key, serialized, ex=max(int(ttl_seconds), 1))
    except Exception as exc:
        mark_redis_unavailable(exc)
