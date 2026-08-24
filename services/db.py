"""Async SQLAlchemy database lifecycle and transaction helpers.

The application owns one :class:`AsyncEngine` per worker process and creates a
short-lived :class:`AsyncSession` for each unit of work.  Sessions are never
shared between concurrent tasks.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .runtime_config import is_production_env

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

_RETRYABLE_SQLSTATES = {
    "40001",  # serialization_failure
    "40P01",  # deadlock_detected
    "55P03",  # lock_not_available
    "08001",  # sqlclient_unable_to_establish_sqlconnection
    "08006",  # connection_failure
    "53300",  # too_many_connections
    "57P03",  # cannot_connect_now
}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value else default


def resolve_database_url() -> str:
    """Return a psycopg 3 async SQLAlchemy URL without reading secret files."""

    configured = _env("DATABASE_URL")
    if configured:
        for prefix in ("postgresql://", "postgres://"):
            if configured.startswith(prefix):
                return "postgresql+psycopg://" + configured[len(prefix) :]
        if configured.startswith("postgresql+psycopg://"):
            return configured
        raise ValueError("DATABASE_URL must use a PostgreSQL URL scheme.")

    user = _env("POSTGRES_USER")
    password = _env("POSTGRES_PASSWORD")
    database = _env("POSTGRES_DB")
    if user is None or password is None or database is None:
        raise ValueError("POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB are required.")

    host = (_env("POSTGRES_HOST", "db") or "db").split(",", 1)[0].strip()
    port = _env("POSTGRES_PORT", "5432") or "5432"
    from urllib.parse import quote_plus

    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}"
    )


def _positive_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _positive_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        value = float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _pool_size() -> int:
    if is_production_env():
        return _positive_int(
            "DB_POOL_MAX_CONN_PRODUCTION",
            _positive_int("DB_POOL_MAX_CONN", 10),
        )
    return _positive_int("DB_POOL_MAX_CONN", 10)


def _warn_if_pool_capacity_is_unsafe(pool_size: int) -> None:
    workers = _positive_int("WEB_CONCURRENCY", 1)
    max_connections_raw = _env("POSTGRES_MAX_CONNECTIONS")
    if max_connections_raw is None:
        return
    try:
        max_connections = int(max_connections_raw)
    except ValueError:
        return
    # Blue/Green deployments can briefly run both colors against the same DB.
    deployment_multiplier = 2 if (_env("BLUE_GREEN_DEPLOYMENT", "false") or "false").lower() in {"1", "true", "yes"} else 1
    reserved = _positive_int("DB_CONNECTION_HEADROOM", 10)
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
    """Lazily create and return this worker's shared async engine."""

    global _engine, _session_factory
    if _engine is not None:
        return _engine

    pool_size = _pool_size()
    _warn_if_pool_capacity_is_unsafe(pool_size)
    _engine = create_async_engine(
        resolve_database_url(),
        pool_size=pool_size,
        max_overflow=0,
        pool_timeout=_positive_float("DB_POOL_ACQUIRE_TIMEOUT_SECONDS", 10.0),
        pool_pre_ping=True,
        pool_recycle=_positive_int("DB_POOL_RECYCLE_SECONDS", 1800),
        echo=(_env("SQLALCHEMY_ECHO", "false") or "false").lower() in {"1", "true", "yes"},
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
    """Return the process-local session factory."""

    get_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield an isolated session and rollback any uncommitted work on exit.

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


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that provides one isolated AsyncSession per request."""

    async with session_scope() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the worker engine during FastAPI shutdown."""

    global _engine, _session_factory
    engine = _engine
    _engine = None
    _session_factory = None
    if engine is not None:
        await engine.dispose()


async def check_database() -> bool:
    """Run the readiness probe through SQLAlchemy's async path."""

    async with session_scope() as session:
        await session.scalar(text("SELECT 1"))
    return True


def is_retryable_db_error(exc: BaseException) -> bool:
    """Identify transient PostgreSQL failures without exposing DBAPI objects."""

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


async def execute_health_query(session: AsyncSession) -> Any:
    """Small shared helper for readiness tests and repository diagnostics."""

    return await session.scalar(text("SELECT 1"))
