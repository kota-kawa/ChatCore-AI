from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
import sqlalchemy as sa
from sqlalchemy import engine_from_config, pool

from services.models import Base

# Alembic設定オブジェクトを取得
# Retrieve Alembic configuration object
config = context.config

# 設定ファイルが存在する場合は、ロギング設定を適用する
# Apply logging configuration if the configuration file exists
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    """Resolve DB URL from env vars used in this project."""
    # 環境変数からデータベースURLを解決する
    # Resolve database URL from environment variables
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        for prefix in ("postgresql://", "postgres://"):
            if database_url.startswith(prefix):
                return "postgresql+psycopg://" + database_url[len(prefix) :]
        if database_url.startswith("postgresql+psycopg://"):
            return database_url
        raise ValueError("DATABASE_URL must use a PostgreSQL URL scheme.")

    # 個別の接続情報環境変数からURLを組み立てる（デフォルトはPostgreSQL）
    # Construct URL from individual connection environment variables (defaults to PostgreSQL)
    user = os.getenv("POSTGRES_USER") or "postgres"
    password = os.getenv("POSTGRES_PASSWORD") or "postgres"
    host = os.getenv("POSTGRES_HOST") or "localhost"
    port = os.getenv("POSTGRES_PORT") or "5432"
    dbname = os.getenv("POSTGRES_DB") or "postgres"
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"


# SQLAlchemyのURL設定を動的に解決した値に書き換える
# Overwrite the SQLAlchemy URL setting with the dynamically resolved value
config.set_main_option("sqlalchemy.url", _resolve_database_url())

# Alembic autogenerate compares the current schema against the same model
# registry used by repositories.  Existing revisions remain immutable.
target_metadata = Base.metadata


class _OfflineInspector:
    """Catalog view for legacy revisions that conditionally inspect the database.

    Several immutable historical revisions use ``sa.inspect(op.get_bind())`` before
    emitting their SQL. Alembic's offline bind is a mock connection and has no catalog.
    The mapped table registry is the only schema source available offline; online runs
    continue to use the real PostgreSQL inspector.
    """

    def get_table_names(self) -> list[str]:
        return list(target_metadata.tables)


class _OfflineExecutionResult:
    """Empty result for immutable data migrations during SQL-only rendering."""

    def mappings(self) -> "_OfflineExecutionResult":
        return self

    def __iter__(self):
        return iter(())


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    # オフラインモードでマイグレーションを実行する
    # Run migrations in 'offline' mode
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    # Immutable historical revisions inspect op.get_bind().  Provide the mapped
    # catalog only for offline SQL rendering, then restore SQLAlchemy's inspector.
    original_inspect = sa.inspect
    offline_bind = context.get_context().bind
    original_execute = offline_bind.execute
    sa.inspect = lambda _subject, *_args, **_kwargs: _OfflineInspector()  # type: ignore[assignment]
    offline_bind.execute = lambda *_args, **_kwargs: _OfflineExecutionResult()  # type: ignore[method-assign]
    try:
        # トランザクションを開始してマイグレーションを実行する
        # Begin a transaction and run migrations
        with context.begin_transaction():
            context.run_migrations()
    finally:
        sa.inspect = original_inspect
        offline_bind.execute = original_execute  # type: ignore[method-assign]


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # オンラインモードでマイグレーションを実行する（エンジンを作成して接続）
    # Run migrations in 'online' mode (create an engine and connect)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        # トランザクションを開始してマイグレーションを実行する
        # Begin a transaction and run migrations
        with context.begin_transaction():
            context.run_migrations()


# 実行モード（オフライン/オンライン）に応じてマイグレーション処理を分岐する
# Dispatch the migration execution based on the offline/online mode
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
