"""Async PostgreSQL catalog and DDL operations for the administrator UI."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.ext.asyncio import AsyncSession

from services.db import session_scope


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def quote_identifier(identifier: str) -> str:
    """Quote one already-validated PostgreSQL identifier with SQLAlchemy."""
    if not _IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError("Invalid SQL identifier.")
    preparer = postgresql_dialect().identifier_preparer
    return preparer.quote(identifier)


def _render_column(column: Mapping[str, object]) -> str:
    name = quote_identifier(str(column["name"]))
    column_type = str(column["type"])
    raw_modifiers = column.get("modifiers", [])
    modifiers = (
        " ".join(str(item) for item in raw_modifiers)
        if isinstance(raw_modifiers, (list, tuple))
        else ""
    )
    return " ".join(part for part in (name, column_type, modifiers) if part)


def build_create_table_sql(
    table_name: str,
    columns: list[dict[str, object]],
    table_options: str = "",
) -> str:
    if table_options:
        raise ValueError("Table options are not supported.")
    if not columns:
        raise ValueError("At least one column is required.")
    rendered = ", ".join(_render_column(column) for column in columns)
    return f"CREATE TABLE {quote_identifier(table_name)} ({rendered})"


def build_drop_table_sql(table_name: str) -> str:
    return f"DROP TABLE {quote_identifier(table_name)}"


def build_add_column_sql(
    table_name: str, column_name: str, column_type: str, modifiers: list[str]
) -> str:
    column: dict[str, object] = {
        "name": column_name,
        "type": column_type,
        "modifiers": modifiers,
    }
    return f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN {_render_column(column)}"


def build_drop_column_sql(table_name: str, column_name: str) -> str:
    return f"ALTER TABLE {quote_identifier(table_name)} DROP COLUMN {quote_identifier(column_name)}"


async def fetch_tables(session: AsyncSession) -> list[str]:
    result = await session.scalars(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
    )
    return list(result.all())


async def fetch_table_columns(
    session: AsyncSession, table_name: str
) -> list[dict[str, object]]:
    result = await session.execute(
        text(
            """
            SELECT
                attr.attname AS column_name,
                pg_catalog.format_type(attr.atttypid, attr.atttypmod) AS column_type,
                NOT attr.attnotnull AS is_nullable,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_index idx
                        WHERE idx.indrelid = rel.oid
                          AND idx.indisprimary
                          AND attr.attnum = ANY(idx.indkey)
                    ) THEN 'PRI'
                    WHEN EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_index idx
                        WHERE idx.indrelid = rel.oid
                          AND idx.indisunique
                          AND attr.attnum = ANY(idx.indkey)
                    ) THEN 'UNI'
                    WHEN EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_index idx
                        WHERE idx.indrelid = rel.oid
                          AND NOT idx.indisunique
                          AND attr.attnum = ANY(idx.indkey)
                    ) THEN 'MUL'
                    ELSE ''
                END AS column_key,
                pg_catalog.pg_get_expr(def.adbin, def.adrelid) AS column_default,
                CASE
                    WHEN attr.attidentity IN ('a', 'd')
                         OR pg_catalog.pg_get_expr(def.adbin, def.adrelid) LIKE 'nextval(%'
                    THEN 'auto_increment'
                    ELSE ''
                END AS extra
            FROM pg_catalog.pg_attribute attr
            JOIN pg_catalog.pg_class rel ON rel.oid = attr.attrelid
            JOIN pg_catalog.pg_namespace nsp ON nsp.oid = rel.relnamespace
            LEFT JOIN pg_catalog.pg_attrdef def
              ON def.adrelid = attr.attrelid AND def.adnum = attr.attnum
            WHERE nsp.nspname = current_schema()
              AND rel.relname = :table_name
              AND attr.attnum > 0
              AND NOT attr.attisdropped
            ORDER BY attr.attnum
            """
        ),
        {"table_name": table_name},
    )
    return [
        {
            "name": row["column_name"],
            "type": row["column_type"],
            "nullable": bool(row["is_nullable"]),
            "key": row["column_key"],
            "default": row["column_default"],
            "extra": row["extra"],
        }
        for row in result.mappings()
    ]


async def fetch_table_preview(
    session: AsyncSession, table_name: str
) -> tuple[list[str], list[tuple]]:
    quoted_table = quote_identifier(table_name)
    result = await session.execute(text(f"SELECT * FROM {quoted_table} LIMIT 100"))
    return list(result.keys()), [tuple(row) for row in result.all()]


async def load_dashboard_data(selected_table: str | None) -> dict[str, Any]:
    async with session_scope() as session:
        tables = await fetch_tables(session)
        column_names: list[str] = []
        column_details: list[dict[str, object]] = []
        existing_columns: list[str] = []
        rows: list[tuple] = []
        missing_selected_table = False

        if selected_table:
            if _IDENTIFIER_PATTERN.fullmatch(selected_table) and selected_table in tables:
                column_names, rows = await fetch_table_preview(session, selected_table)
                column_details = await fetch_table_columns(session, selected_table)
                existing_columns = [str(column["name"]) for column in column_details]
            else:
                missing_selected_table = True
                selected_table = None

        return {
            "tables": tables,
            "selected_table": selected_table,
            "column_names": column_names,
            "column_details": column_details,
            "existing_columns": existing_columns,
            "rows": rows,
            "missing_selected_table": missing_selected_table,
        }


async def create_table(
    table_name: str,
    columns: list[dict[str, object]],
    table_options: str = "",
) -> None:
    statement = build_create_table_sql(table_name, columns, table_options)
    async with session_scope() as session:
        async with session.begin():
            await session.execute(text(statement))


async def drop_table_if_exists(table_name: str) -> bool:
    async with session_scope() as session:
        async with session.begin():
            tables = await fetch_tables(session)
            if table_name not in tables:
                return False
            await session.execute(text(build_drop_table_sql(table_name)))
            return True


async def add_column_if_valid(
    table_name: str,
    column_name: str,
    column_type: str,
    modifiers: list[str],
) -> str:
    async with session_scope() as session:
        async with session.begin():
            tables = await fetch_tables(session)
            if table_name not in tables:
                return "missing_table"
            columns = await fetch_table_columns(session, table_name)
            if column_name.lower() in {str(column["name"]).lower() for column in columns}:
                return "duplicate_column"
            await session.execute(
                text(build_add_column_sql(table_name, column_name, column_type, modifiers))
            )
            return "ok"


async def drop_column_if_valid(
    table_name: str, column_name: str
) -> tuple[str, str | None]:
    async with session_scope() as session:
        async with session.begin():
            tables = await fetch_tables(session)
            if table_name not in tables:
                return "missing_table", None
            columns = await fetch_table_columns(session, table_name)
            lookup = {str(column["name"]).lower(): str(column["name"]) for column in columns}
            target_column = lookup.get(column_name.lower())
            if target_column is None:
                return "missing_column", None
            if len(columns) <= 1:
                return "last_column", None
            await session.execute(text(build_drop_column_sql(table_name, target_column)))
            return "ok", target_column
