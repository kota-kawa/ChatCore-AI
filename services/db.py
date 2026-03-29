import atexit
import os
import threading
from types import TracebackType
from typing import Any

from .runtime_config import is_production_env

# テスト環境では psycopg2 が未導入の場合があるため遅延フォールバックする
# Allow graceful fallback when psycopg2 is unavailable in test environments.
try:
    import psycopg2
    from psycopg2 import Error, extras
    from psycopg2.pool import ThreadedConnectionPool
except ModuleNotFoundError:  # pragma: no cover - optional for test envs
    psycopg2 = None
    Error = Exception
    extras = None
    ThreadedConnectionPool = None


_pool_lock = threading.Lock()
DbConfig = dict[str, str | int]
PoolKey = tuple[tuple[str, ...], str, str, str, int, int, int]

_connection_pool: Any | None = None
_connection_pool_key: PoolKey | None = None
_RETRYABLE_DB_PG_CODES = {
    # serialization_failure
    "40001",
    # deadlock_detected
    "40P01",
    # lock_not_available
    "55P03",
    # connection_failure, sqlclient_unable_to_establish_sqlconnection
    "08006",
    "08001",
    # too_many_connections
    "53300",
    # cannot_connect_now
    "57P03",
}


class _ConnectionProxy:
    # プールへ返却済み接続の再利用を防ぐ薄いラッパー
    # Lightweight wrapper that prevents reuse after returning to the pool.
    """Pooled connection wrapper with dictionary=True cursor support."""

    def __init__(self, connection: Any, connection_pool: Any) -> None:
        self._connection = connection
        self._connection_pool = connection_pool
        self._returned = False

    def _ensure_open(self) -> None:
        if self._returned or self._connection is None:
            raise RuntimeError("Connection already returned to pool.")

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_open()
        dictionary = kwargs.pop("dictionary", False)
        if dictionary:
            # mysqlclient 互換の dictionary=True を psycopg2 の RealDictCursor に変換する
            # Translate mysqlclient-style dictionary=True into psycopg2 RealDictCursor.
            if extras is None:
                raise RuntimeError("psycopg2 extras are required for dictionary cursors.")
            kwargs["cursor_factory"] = extras.RealDictCursor
        return self._connection.cursor(*args, **kwargs)

    def close(self) -> None:
        if self._returned or self._connection is None:
            return

        connection = self._connection
        connection_pool = self._connection_pool
        self._connection = None
        self._connection_pool = None
        self._returned = True

        # 返却前にロールバックし、汚れたトランザクション状態を持ち越さない
        # Roll back before returning so dirty transactions are not leaked.
        close_physical = bool(getattr(connection, "closed", 0))
        if not close_physical:
            rolled_back = rollback_connection(connection)
            if not rolled_back:
                close_physical = True

        try:
            connection_pool.putconn(connection, close=close_physical)
        except Exception:  # pragma: no cover - depends on env/pool state
            try:
                connection.close()
            except Exception:
                pass

    def __enter__(self) -> "_ConnectionProxy":
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self.close()
        return False

    def __del__(self) -> None:  # pragma: no cover - GC timing is nondeterministic
        try:
            self.close()
        except Exception:
            pass

    def __getattr__(self, name: str) -> Any:
        self._ensure_open()
        return getattr(self._connection, name)


def _get_env(name: str, fallback_name: str, default: str | None) -> str | None:
    # 新旧環境変数を順番に見て互換性を維持する
    # Resolve value from primary and legacy env vars for backward compatibility.
    value = os.environ.get(name)
    if value:
        return value
    value = os.environ.get(fallback_name)
    if value:
        return value
    return default


def rollback_connection(connection: Any) -> bool:
    # 例外処理時に安全にロールバックし、失敗しても二次例外を出さない
    # Roll back safely during exception handling and swallow rollback failures.
    if connection is None:
        return False
    try:
        connection.rollback()
        return True
    except Exception:
        return False


def is_retryable_db_error(exc: BaseException) -> bool:
    # DB例外から再試行可能性を判定する
    # Infer whether a DB error is retryable.
    pgcode = getattr(exc, "pgcode", None)
    if isinstance(pgcode, str) and pgcode in _RETRYABLE_DB_PG_CODES:
        return True

    if Error is not Exception and isinstance(exc, Error):
        exc_name = exc.__class__.__name__
        if exc_name in {"OperationalError", "InterfaceError"}:
            return True

    return False


def _get_db_hosts() -> list[str]:
    env_host = os.environ.get("POSTGRES_HOST") or os.environ.get("MYSQL_HOST")
    if env_host:
        hosts = [host.strip() for host in env_host.split(",") if host.strip()]
        # If a single docker-compose host is provided, add safe local fallbacks.
        if len(hosts) == 1 and hosts[0] == "db":
            hosts.extend(["localhost", "127.0.0.1", "host.docker.internal"])
        return hosts
    # Prefer docker-compose's default service name but allow local dev fallback.
    return ["db", "localhost", "127.0.0.1", "host.docker.internal"]


def _get_db_config() -> DbConfig:
    user = _get_env("POSTGRES_USER", "MYSQL_USER", None)
    password = _get_env("POSTGRES_PASSWORD", "MYSQL_PASSWORD", None)
    dbname = _get_env("POSTGRES_DB", "MYSQL_DATABASE", None)

    if not all([user, password, dbname]):
        raise ValueError("Database configuration (USER, PASSWORD, DB) must be set in environment variables.")

    return {
        "host": _get_env("POSTGRES_HOST", "MYSQL_HOST", "db"),
        "user": user,
        "password": password,
        "dbname": dbname,
        "port": int(_get_env("POSTGRES_PORT", "MYSQL_PORT", "5432")),
    }


def _get_pool_bounds() -> tuple[int, int]:
    if is_production_env():
        min_conn_raw = os.environ.get(
            "DB_POOL_MIN_CONN_PRODUCTION",
            os.environ.get("DB_POOL_MIN_CONN", "1"),
        )
        max_conn_raw = os.environ.get(
            "DB_POOL_MAX_CONN_PRODUCTION",
            os.environ.get("DB_POOL_MAX_CONN", "10"),
        )
    else:
        min_conn_raw = os.environ.get("DB_POOL_MIN_CONN", "1")
        max_conn_raw = os.environ.get("DB_POOL_MAX_CONN", "10")

    min_conn = int(min_conn_raw)
    max_conn = int(max_conn_raw)
    if min_conn < 1:
        raise ValueError("DB_POOL_MIN_CONN must be >= 1.")
    if max_conn < min_conn:
        raise ValueError("DB_POOL_MAX_CONN must be >= DB_POOL_MIN_CONN.")
    return min_conn, max_conn


def _build_pool_key(
    config: DbConfig, hosts: list[str], min_conn: int, max_conn: int
) -> PoolKey:
    return (
        tuple(hosts),
        config["user"],
        config["password"],
        config["dbname"],
        config["port"],
        min_conn,
        max_conn,
    )


def _build_connection_pool(
    config: DbConfig, hosts: list[str], min_conn: int, max_conn: int
) -> Any:
    if ThreadedConnectionPool is None:
        raise RuntimeError("psycopg2 ThreadedConnectionPool is required to connect to the database.")

    first_exc = None
    # 複数ホストを順に試し、最初に接続成功したプールを採用する
    # Try hosts in order and keep the first successfully validated pool.
    for host in hosts:
        candidate_config = dict(config)
        candidate_config["host"] = host
        pool_instance = None
        try:
            pool_instance = ThreadedConnectionPool(min_conn, max_conn, **candidate_config)
            validation_conn = pool_instance.getconn()
            pool_instance.putconn(validation_conn)
            return pool_instance
        except Exception as exc:  # pragma: no cover - depends on env
            if first_exc is None:
                first_exc = exc
            if pool_instance is not None:
                try:
                    pool_instance.closeall()
                except Exception:
                    pass
            continue

    if first_exc is not None:
        raise first_exc
    raise RuntimeError("Database connection pool initialization failed without an exception.")


def _get_connection_pool() -> Any:
    global _connection_pool, _connection_pool_key

    config = _get_db_config()
    hosts = _get_db_hosts()
    min_conn, max_conn = _get_pool_bounds()
    pool_key = _build_pool_key(config, hosts, min_conn, max_conn)
    old_pool = None
    new_pool = None

    with _pool_lock:
        if _connection_pool is not None and _connection_pool_key == pool_key:
            return _connection_pool

        # 設定が変わった場合は新プールへ差し替え、旧プールはロック外で閉じる
        # Replace pool on config change and close previous pool outside the lock.
        old_pool = _connection_pool
        new_pool = _build_connection_pool(config, hosts, min_conn, max_conn)
        _connection_pool = new_pool
        _connection_pool_key = pool_key

    if old_pool is not None:
        try:
            old_pool.closeall()
        except Exception:
            pass

    return new_pool


def close_db_pool() -> None:
    # プロセス終了時やシャットダウン時に全コネクションを確実に解放する
    # Ensure all pooled connections are released on shutdown/exit.
    """Close all pooled DB connections."""
    global _connection_pool, _connection_pool_key

    with _pool_lock:
        pool_instance = _connection_pool
        _connection_pool = None
        _connection_pool_key = None

    if pool_instance is None:
        return

    try:
        pool_instance.closeall()
    except Exception:  # pragma: no cover - depends on env
        pass


atexit.register(close_db_pool)


def get_db_connection() -> _ConnectionProxy:
    # プールから 1 接続を貸し出し、close() 時に自動返却されるプロキシを返す
    # Borrow a pooled connection and return a proxy that puts it back on close().
    """PostgreSQL への接続を返す (connection pool backed)."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required to connect to the database.")

    connection_pool = _get_connection_pool()
    connection = connection_pool.getconn()
    return _ConnectionProxy(connection, connection_pool)
