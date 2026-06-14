from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    """Resolve DB URL from env vars used in this project."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    user = os.getenv("POSTGRES_USER") or os.getenv("MYSQL_USER") or "postgres"
    password = os.getenv("POSTGRES_PASSWORD") or os.getenv("MYSQL_PASSWORD") or "postgres"
    host = os.getenv("POSTGRES_HOST") or os.getenv("MYSQL_HOST") or "localhost"
    port = os.getenv("POSTGRES_PORT") or os.getenv("MYSQL_PORT") or "5432"
    dbname = os.getenv("POSTGRES_DB") or os.getenv("MYSQL_DATABASE") or "postgres"
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"


config.set_main_option("sqlalchemy.url", _resolve_database_url())

target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
