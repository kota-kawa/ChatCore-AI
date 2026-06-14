from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

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
        return database_url

    # 個別の接続情報環境変数からURLを組み立てる（デフォルトはPostgreSQL）
    # Construct URL from individual connection environment variables (defaults to PostgreSQL)
    user = os.getenv("POSTGRES_USER") or os.getenv("MYSQL_USER") or "postgres"
    password = os.getenv("POSTGRES_PASSWORD") or os.getenv("MYSQL_PASSWORD") or "postgres"
    host = os.getenv("POSTGRES_HOST") or os.getenv("MYSQL_HOST") or "localhost"
    port = os.getenv("POSTGRES_PORT") or os.getenv("MYSQL_PORT") or "5432"
    dbname = os.getenv("POSTGRES_DB") or os.getenv("MYSQL_DATABASE") or "postgres"
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"


# SQLAlchemyのURL設定を動的に解決した値に書き換える
# Overwrite the SQLAlchemy URL setting with the dynamically resolved value
config.set_main_option("sqlalchemy.url", _resolve_database_url())

# 自動マイグレーション用のメタデータオブジェクト（今回はNone）
# Metadata object for autogenerate migrations (set to None here)
target_metadata = None


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
    )

    # トランザクションを開始してマイグレーションを実行する
    # Begin a transaction and run migrations
    with context.begin_transaction():
        context.run_migrations()


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
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

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
