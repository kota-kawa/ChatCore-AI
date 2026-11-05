"""非同期 SQLAlchemy のデータベース接続の管理（エンジン・セッション・トランザクション）と、再試行可能なエラーの判定を担う。
ワーカープロセスごとに AsyncEngine を 1 つ持ち、作業単位ごとに短命の AsyncSession を作る。セッションは並行タスク間で共有しない。

Async SQLAlchemy database lifecycle and transaction helpers.

The application owns one :class:`AsyncEngine` per worker process and creates a
short-lived :class:`AsyncSession` for each unit of work.  Sessions are never
shared between concurrent tasks.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .env_settings import env_bool, env_float, env_int, env_text
from .runtime_config import is_production_env

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# 日本語: 一時的な失敗として再試行してよい PostgreSQL の SQLSTATE（直列化失敗・デッドロック・接続系など）。
# English: PostgreSQL SQLSTATE codes treated as transient and safe to retry (serialization failures, deadlocks, connection issues).
_RETRYABLE_SQLSTATES = {
    # 直列化失敗
    "40001",  # serialization_failure
    # デッドロック検出
    "40P01",  # deadlock_detected
    # ロック取得不可
    "55P03",  # lock_not_available
    # 接続を確立できない
    "08001",  # sqlclient_unable_to_establish_sqlconnection
    # 接続障害
    "08006",  # connection_failure
    # 接続数超過
    "53300",  # too_many_connections
    # 現在は接続できない
    "57P03",  # cannot_connect_now
}


def resolve_database_url() -> str:
    """psycopg 3 用の非同期 SQLAlchemy URL を返す。シークレットファイルは読まない。
    DATABASE_URL があればそれを正規化し、なければ POSTGRES_* の個別設定から組み立てる。

    Return a psycopg 3 async SQLAlchemy URL without reading secret files.
    Normalizes DATABASE_URL when set; otherwise builds the URL from the POSTGRES_* settings.
    """

    configured = env_text("DATABASE_URL")
    if configured:
        for prefix in ("postgresql://", "postgres://"):
            if configured.startswith(prefix):
                return "postgresql+psycopg://" + configured[len(prefix) :]
        if configured.startswith("postgresql+psycopg://"):
            return configured
        raise ValueError("DATABASE_URL must use a PostgreSQL URL scheme.")

    user = env_text("POSTGRES_USER")
    password = env_text("POSTGRES_PASSWORD")
    database = env_text("POSTGRES_DB")
    if user is None or password is None or database is None:
        raise ValueError("POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB are required.")

    host = (env_text("POSTGRES_HOST", "db") or "db").split(",", 1)[0].strip()
    port = env_text("POSTGRES_PORT", "5432") or "5432"
    from urllib.parse import quote_plus

    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}"
    )


# 日本語: 接続プールの上限。本番では本番専用の設定があればそれを優先する。
# English: Connection pool size; production prefers its dedicated setting when present.
def _pool_size() -> int:
    if is_production_env():
        return env_int(
            "DB_POOL_MAX_CONN_PRODUCTION",
            env_int("DB_POOL_MAX_CONN", 10),
        )
    return env_int("DB_POOL_MAX_CONN", 10)


# 日本語: 全ワーカーのプール合計（ブルーグリーン時は 2 色分）と予備枠が PostgreSQL の max_connections 以上なら警告する。
# English: Warn when the total pool across workers (two colors during blue/green) plus headroom reaches PostgreSQL's max_connections.
def _warn_if_pool_capacity_is_unsafe(pool_size: int) -> None:
    workers = env_int("WEB_CONCURRENCY", 1)
    max_connections_raw = env_text("POSTGRES_MAX_CONNECTIONS")
    if max_connections_raw is None:
        return
    try:
        max_connections = int(max_connections_raw)
    except ValueError:
        return
    # 日本語: ブルーグリーン配備では、短時間だけ両方の色が同じ DB に接続する。
    # Blue/Green deployments can briefly run both colors against the same DB.
    deployment_multiplier = 2 if env_bool("BLUE_GREEN_DEPLOYMENT") else 1
    reserved = env_int("DB_CONNECTION_HEADROOM", 10)
    required = deployment_multiplier * workers * pool_size + reserved
    if required >= max_connections:
        logger.warning(
            "Configured DB capacity may be unsafe: %s workers x %s pool connections "
            "x %s deployment colors + %s headroom = %s, PostgreSQL max_connections=%s.",
            workers,
            pool_size,
            deployment_multiplier,
            reserved,
            required,
            max_connections,
        )


def get_engine() -> AsyncEngine:
    """このワーカーで共有する非同期エンジンを、初回呼び出し時に作って返す（以降は同じものを返す）。
    プールは max_overflow=0 で上限を固定し、使用前の死活確認（pre_ping）と定期的な再生成を有効にしている。

    Lazily create and return this worker's shared async engine.
    The pool is capped (max_overflow=0), with pre-ping and periodic recycling enabled.
    """

    global _engine, _session_factory
    if _engine is not None:
        return _engine

    pool_size = _pool_size()
    _warn_if_pool_capacity_is_unsafe(pool_size)
    _engine = create_async_engine(
        resolve_database_url(),
        pool_size=pool_size,
        max_overflow=0,
        pool_timeout=env_float("DB_POOL_ACQUIRE_TIMEOUT_SECONDS", 10.0),
        pool_pre_ping=True,
        pool_recycle=env_int("DB_POOL_RECYCLE_SECONDS", 1800),
        echo=env_bool("SQLALCHEMY_ECHO"),
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """プロセス内で共有するセッションファクトリを返す（未作成ならエンジンと一緒に作る）。

    Return the process-local session factory.
    """

    get_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """独立したセッションを提供し、終了時にコミットされていない作業をロールバックする。

    コミットはユースケースの境界で明示的に行う設計にしている。複数ステップのサービスから呼ばれた
    リポジトリが、処理の途中でコミットしてしまうのを防ぐため。

    Yield an isolated session and rollback any uncommitted work on exit.

    Commit is deliberately explicit at the use-case boundary.  This prevents a
    repository called by a multi-step service from committing half a workflow.
    """

    session = get_session_factory()()
    try:
        yield session
    except BaseException:
        await session.rollback()
        raise
    finally:
        if session.in_transaction():
            await session.rollback()
        await session.close()


async def dispose_engine() -> None:
    """FastAPI のシャットダウン時に、このワーカーのエンジンを破棄して接続を閉じる。

    Dispose the worker engine during FastAPI shutdown.
    """

    global _engine, _session_factory
    engine = _engine
    _engine = None
    _session_factory = None
    if engine is not None:
        await engine.dispose()


async def check_database() -> bool:
    """SQLAlchemy の非同期経路で SELECT 1 を実行し、DB に接続できるか確認する（レディネス用）。

    Run the readiness probe through SQLAlchemy's async path.
    """

    async with session_scope() as session:
        await session.scalar(text("SELECT 1"))
    return True


def is_retryable_db_error(exc: BaseException) -> bool:
    """一時的な PostgreSQL の障害かを判定する。DBAPI のオブジェクトは外へ見せない。
    例外の連鎖を最大 3 段までたどって SQLSTATE を調べ、なければ接続が無効化された DBAPI エラーかで判断する。

    Identify transient PostgreSQL failures without exposing DBAPI objects.
    Follows the exception chain up to three levels for a SQLSTATE, then falls back to invalidated-connection DBAPI errors.
    """

    current: BaseException | None = exc
    for _ in range(3):
        if current is None:
            break
        sqlstate = getattr(current, "sqlstate", None)
        if sqlstate in _RETRYABLE_SQLSTATES:
            return True
        orig = getattr(current, "orig", None)
        current = orig if isinstance(orig, BaseException) else None
    return isinstance(exc, (OperationalError, DBAPIError)) and bool(getattr(exc, "connection_invalidated", False))

