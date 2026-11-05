"""管理者画面向けに、PostgreSQL のテーブル一覧・列情報・先頭行の取得と、テーブル/列の作成・削除 DDL を実行する。

blueprints/admin/views.py から呼ばれる。識別子は検証したうえで引用符付きで SQL に埋め込む。

Async PostgreSQL catalog and DDL operations for the administrator UI.
Called from blueprints/admin/views.py; identifiers are validated and quoted before being placed in SQL.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.ext.asyncio import AsyncSession

from services.db import session_scope

# 日本語: DDL には識別子をバインド変数で渡せないため、英数字と _ のみ・63 文字以内(PostgreSQL の上限)に限定して SQL へ埋め込む。
# English: DDL cannot take identifiers as bind parameters, so only letters, digits and _ up to 63 chars (PostgreSQL's limit) are inlined.
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def quote_identifier(identifier: str) -> str:
    # 検証済みPostgreSQL識別子をSQLAlchemyで引用する。
    """Quote one already-validated PostgreSQL identifier with SQLAlchemy."""
    if not _IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError("Invalid SQL identifier.")
    preparer = postgresql_dialect().identifier_preparer
    return preparer.quote(identifier)


# 日本語: 列定義(名前 型 修飾子)を 1 つの文字列にする。名前は検証済みの識別子に限る。型と修飾子は、呼び出し
# 側(views の _parse_column_definition)で解析済みの値を渡す前提。
# English: Renders one column definition. The name must be a validated identifier; the type and modifiers are expected to come
# already parsed by the caller (views._parse_column_definition).
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
    # 日本語: 任意の SQL 断片が紛れ込まないよう、テーブルオプションは受け付けない。
    # English: Table options are rejected so no arbitrary SQL fragment can slip in.
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


# 日本語: プレビューは最大 100 行に制限する。
# English: The preview is capped at 100 rows.
async def fetch_table_preview(
    session: AsyncSession, table_name: str
) -> tuple[list[str], list[tuple]]:
    quoted_table = quote_identifier(table_name)
    result = await session.execute(text(f"SELECT * FROM {quoted_table} LIMIT 100"))
    return list(result.keys()), [tuple(row) for row in result.all()]


# 日本語: 管理画面の表示用に、テーブル一覧と選択中テーブルの列・先頭行をまとめて返す。
# 選択名が存在しない/不正な場合は選択を外し、missing_selected_table で知らせる。
# English: Returns the table list plus columns and preview rows for the selected table in one payload.
# An unknown or invalid selection is cleared and flagged via missing_selected_table.
async def load_dashboard_data(selected_table: str | None) -> dict[str, Any]:
    async with session_scope() as session:
        tables = await fetch_tables(session)
        column_names: list[str] = []
        column_details: list[dict[str, object]] = []
        existing_columns: list[str] = []
        rows: list[tuple] = []
        missing_selected_table = False

        if selected_table:
            # 日本語: 一覧に実在するテーブル名だけを SQL に使う(クエリ文字列由来の値を直接埋め込まない)。
            # English: Only names that exist in the table list reach SQL; the query-string value is never inlined as is.
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
    async with session_scope() as session, session.begin():
        await session.execute(text(statement))


async def drop_table_if_exists(table_name: str) -> bool:
    async with session_scope() as session, session.begin():
        tables = await fetch_tables(session)
        if table_name not in tables:
            return False
        await session.execute(text(build_drop_table_sql(table_name)))
        return True


# 日本語: 同一トランザクション内で存在確認と DDL を行い、結果を "ok" / "missing_table" / "duplicate_column" の状態文字列で返す。
# 列名の重複判定は大文字小文字を区別しない(PostgreSQL は引用なしの識別子を小文字に畳むため)。
# English: Checks and runs the DDL in one transaction and returns a status string ("ok" / "missing_table" / "duplicate_column").
# Duplicate detection is case-insensitive because PostgreSQL folds unquoted identifiers to lower case.
async def add_column_if_valid(
    table_name: str,
    column_name: str,
    column_type: str,
    modifiers: list[str],
) -> str:
    async with session_scope() as session, session.begin():
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


# 日本語: 列削除。表や列が無い場合と、最後の 1 列を消そうとした場合(列 0 のテーブルを作らせない)は DDL を実行せず状態文字列を返す。
# English: Drops a column. A missing table/column, or an attempt to drop the last column (which would leave a zero-column table),
# returns a status string without running DDL.
async def drop_column_if_valid(
    table_name: str, column_name: str
) -> tuple[str, str | None]:
    async with session_scope() as session, session.begin():
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
