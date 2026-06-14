import inspect
import logging
import os
import re
from functools import wraps
from typing import Optional
from urllib.parse import urlencode

from fastapi import Depends, Request
from starlette.responses import RedirectResponse

from services.async_utils import run_blocking
from services.api_errors import DEFAULT_RETRY_AFTER_SECONDS, parse_retry_after_seconds
from services.auth_limits import (
    AuthLimitService,
    consume_admin_login_limit,
    get_auth_limit_service,
)
from services.db import Error, get_db_connection
from services.security import verify_password
from services.session_middleware import rotate_session_identifier
from services.web import (
    flash,
    frontend_url,
    get_flashed_messages,
    get_json,
    jsonify,
    jsonify_rate_limited,
    log_and_internal_server_error,
    redirect_to_frontend,
    sanitize_next_path,
    url_for,
)

from . import admin_bp

try:
    from psycopg2 import sql as pg_sql
except ModuleNotFoundError:  # pragma: no cover - optional for test envs
    pg_sql = None

ADMIN_PASSWORD_HASH = (os.getenv("ADMIN_PASSWORD_HASH") or "").strip()
logger = logging.getLogger(__name__)
SQL_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
SIMPLE_COLUMN_TYPE_PATTERNS = (
    re.compile(
        r"^(?:SMALLINT|INTEGER|INT|BIGINT|SERIAL|BIGSERIAL|TEXT|BOOLEAN|BOOL|DATE|JSON|JSONB|UUID|BYTEA|REAL|DOUBLE PRECISION)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^TIMESTAMP(?:\s*\(\s*\d{1,2}\s*\))?(?:\s+(?:WITH|WITHOUT)\s+TIME\s+ZONE)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"^TIMESTAMPTZ\b", re.IGNORECASE),
    re.compile(r"^VARCHAR\s*\(\s*[1-9]\d{0,4}\s*\)", re.IGNORECASE),
    re.compile(r"^CHARACTER\s+VARYING\s*\(\s*[1-9]\d{0,4}\s*\)", re.IGNORECASE),
    re.compile(r"^CHAR\s*\(\s*[1-9]\d{0,4}\s*\)", re.IGNORECASE),
    re.compile(r"^NUMERIC\s*\(\s*\d{1,4}\s*(?:,\s*\d{1,4}\s*)?\)", re.IGNORECASE),
    re.compile(r"^DECIMAL\s*\(\s*\d{1,4}\s*(?:,\s*\d{1,4}\s*)?\)", re.IGNORECASE),
)
DEFAULT_VALUE_PATTERN = re.compile(
    r"^(NULL|TRUE|FALSE|CURRENT_DATE|CURRENT_TIMESTAMP|NOW\(\)|-?\d+(?:\.\d+)?|'(?:''|[^'])*')(?=\s|$)",
    re.IGNORECASE,
)


# リクエストから認証制限サービスを解決するヘルパー関数
# Helper function to resolve the AuthLimitService instance from the request.
def _resolve_auth_limit_service(
    request: Request,
    service: AuthLimitService | None,
) -> AuthLimitService:
    if isinstance(service, AuthLimitService):
        return service
    return get_auth_limit_service(request)


# 入力された管理者パスワードを検証する関数
# Verify the provided password against the administrator password hash.
def _verify_admin_password(password: str) -> bool:
    if not ADMIN_PASSWORD_HASH:
        return False
    return verify_password(password, ADMIN_PASSWORD_HASH)


# psycopg2.sqlモジュールがインストールされているか確認し取得する関数
# Verify that psycopg2.sql is available and return it for dynamic SQL formatting.
def _require_pg_sql():
    if pg_sql is None:  # pragma: no cover - depends on optional dependency
        raise RuntimeError("psycopg2 is required for admin SQL composition.")
    return pg_sql


# SQL識別子（テーブル名やカラム名）を安全にエスケープするオブジェクトを生成する関数
# Construct a psycopg2.sql.Identifier object to safely escape SQL identifiers.
def _sql_identifier(name: str):
    return _require_pg_sql().Identifier(name)


# SQLフラグメント末尾のセミコロンや前後の余白を除去する関数
# Strip trailing semicolons and leading/trailing whitespace from a SQL fragment.
def _normalize_fragment(fragment: str) -> str:
    return fragment.rstrip(";").strip()


# SQLフラグメントにセミコロンが含まれるか（複数ステートメントインジェクションの兆候）を判定する関数
# Check if a SQL fragment contains a semicolon, indicating potentially multiple statements.
def _has_multiple_statements(fragment: str) -> bool:
    return ";" in fragment


# SQL内の余分な空白や改行を単一スペースに正規化する関数
# Normalize whitespace sequences in a SQL fragment into a single space.
def _normalize_sql_whitespace(fragment: str) -> str:
    return re.sub(r"\s+", " ", fragment).strip()


# 文字列が安全なSQL識別子パターン（英数字・アンダースコア）に一致するか検証する関数
# Determine if a string is a syntactically valid and safe SQL identifier.
def _is_safe_sql_identifier(name: str) -> bool:
    return bool(SQL_IDENTIFIER_PATTERN.fullmatch(name))


# SQL識別子の安全性を検証し、不正な場合はエラーを投げる関数
# Validate a SQL identifier string, throwing ValueError if it contains unsafe characters.
def _validate_sql_identifier(name: str, label: str) -> str:
    normalized = name.strip()
    if not _is_safe_sql_identifier(normalized):
        raise ValueError(f"Invalid {label}.")
    return normalized


# カンマ区切りのSQLリストを、引用符や括弧のネストを考慮して分割する関数
# Split a comma-separated SQL fragment, respecting nested single quotes and parentheses.
def _split_sql_csv(fragment: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_quote = False
    i = 0

    while i < len(fragment):
        ch = fragment[i]
        if ch == "'":
            current.append(ch)
            if in_quote and i + 1 < len(fragment) and fragment[i + 1] == "'":
                current.append(fragment[i + 1])
                i += 2
                continue
            in_quote = not in_quote
            i += 1
            continue

        if not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    raise ValueError("Invalid column definition.")
            elif ch == "," and depth == 0:
                part = "".join(current).strip()
                if not part:
                    raise ValueError("Invalid column definition.")
                parts.append(part)
                current = []
                i += 1
                continue

        current.append(ch)
        i += 1

    if in_quote or depth != 0:
        raise ValueError("Invalid column definition.")

    tail = "".join(current).strip()
    if not tail:
        raise ValueError("Invalid column definition.")
    parts.append(tail)
    return parts


# カラム定義文字列からデータ型部分を取り出す関数
# Extract and normalize the SQL data type from the beginning of a column definition fragment.
def _consume_column_type(fragment: str) -> tuple[str, str]:
    for pattern in SIMPLE_COLUMN_TYPE_PATTERNS:
        match = pattern.match(fragment)
        if match is None:
            continue
        matched = match.group(0)
        remainder = fragment[match.end() :].strip()
        return _normalize_sql_whitespace(matched).upper(), remainder
    raise ValueError("Unsupported column type.")


# カラム定義の DEFAULT 句からデフォルト値を抽出する関数
# Parse and consume the literal or function value immediately following a DEFAULT SQL keyword.
def _consume_default_value(fragment: str) -> tuple[str, str]:
    match = DEFAULT_VALUE_PATTERN.match(fragment)
    if match is None:
        raise ValueError("Unsupported DEFAULT value.")
    matched = match.group(0)
    remainder = fragment[match.end() :].strip()
    normalized = matched if matched.startswith("'") else matched.upper()
    return normalized, remainder


# 単一のカラム定義（名称、型、制約）をパースする関数
# Parse a single column definition string into its name, type, and SQL constraints/modifiers.
def _parse_column_definition(definition: str) -> dict[str, object]:
    parts = definition.strip().split(None, 1)
    if len(parts) != 2:
        raise ValueError("Invalid column definition.")

    column_name = _validate_sql_identifier(parts[0], "column name")
    column_type, remainder = _consume_column_type(parts[1].strip())
    modifiers: list[str] = []
    seen_tokens: set[str] = set()

    while remainder:
        not_null_match = re.match(r"^NOT\s+NULL(?=\s|$)", remainder, re.IGNORECASE)
        null_match = re.match(r"^NULL(?=\s|$)", remainder, re.IGNORECASE)
        primary_key_match = re.match(r"^PRIMARY\s+KEY(?=\s|$)", remainder, re.IGNORECASE)
        unique_match = re.match(r"^UNIQUE(?=\s|$)", remainder, re.IGNORECASE)
        default_match = re.match(r"^DEFAULT\s+", remainder, re.IGNORECASE)

        if not_null_match:
            if "NULLABILITY" in seen_tokens:
                raise ValueError("Duplicate NULL constraint.")
            seen_tokens.add("NULLABILITY")
            modifiers.append("NOT NULL")
            remainder = remainder[not_null_match.end() :].strip()
            continue
        if null_match:
            if "NULLABILITY" in seen_tokens:
                raise ValueError("Duplicate NULL constraint.")
            seen_tokens.add("NULLABILITY")
            modifiers.append("NULL")
            remainder = remainder[null_match.end() :].strip()
            continue
        if primary_key_match:
            if "PRIMARY KEY" in seen_tokens:
                raise ValueError("Duplicate PRIMARY KEY constraint.")
            seen_tokens.add("PRIMARY KEY")
            modifiers.append("PRIMARY KEY")
            remainder = remainder[primary_key_match.end() :].strip()
            continue
        if unique_match:
            if "UNIQUE" in seen_tokens:
                raise ValueError("Duplicate UNIQUE constraint.")
            seen_tokens.add("UNIQUE")
            modifiers.append("UNIQUE")
            remainder = remainder[unique_match.end() :].strip()
            continue
        if default_match:
            if "DEFAULT" in seen_tokens:
                raise ValueError("Duplicate DEFAULT constraint.")
            seen_tokens.add("DEFAULT")
            default_value, remainder = _consume_default_value(remainder[default_match.end() :].strip())
            modifiers.append(f"DEFAULT {default_value}")
            continue
        raise ValueError("Unsupported column constraint.")

    return {
        "name": column_name,
        "type": column_type,
        "modifiers": modifiers,
    }


# カンマで区切られた複数のカラム定義全体をパースする関数
# Parse a comma-separated list of column definitions into a list of structured column dictionaries.
def _parse_column_definitions(column_definitions: str) -> list[dict[str, object]]:
    parsed_columns = [_parse_column_definition(part) for part in _split_sql_csv(column_definitions)]
    if not parsed_columns:
        raise ValueError("At least one column is required.")
    return parsed_columns


# テーブルオプション（本実装では未サポート）を検証する関数
# Validate table option fragments (options are not supported in this implementation).
def _validate_table_options(table_options: str) -> str:
    normalized = _normalize_fragment(table_options)
    if not normalized:
        return ""
    raise ValueError("Table options are not supported.")


# カラムデータ辞書から安全なSQLクエリフラグメントを組み立てる関数
# Construct a safely formatted psycopg2.sql statement for a single column definition.
def _build_column_sql(column_definition: dict[str, object]):
    psql = _require_pg_sql()
    statement = psql.SQL("{} {}").format(
        _sql_identifier(str(column_definition["name"])),
        psql.SQL(str(column_definition["type"])),
    )
    for modifier in column_definition["modifiers"]:
        statement += psql.SQL(" ") + psql.SQL(str(modifier))
    return statement


# フロントエンドの管理者用ダッシュボードURLを取得するヘルパー関数
# Helper to construct the absolute frontend URL for the administrator dashboard page.
def frontend_admin_dashboard_url(request: Request, **params) -> str:
    return frontend_url(url_for(request, "admin.dashboard", **params))


# 管理者セッションが必要なルートを保護するデコレータ
# Route decorator that enforces an active administrator session before allowing access.
def admin_required(view_func):
    @wraps(view_func)
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if request is None:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
        if request is None:
            raise RuntimeError("Request is required for admin routes")

        if not request.session.get("is_admin"):
            next_path = request.url.path
            if request.url.query:
                next_path = f"{next_path}?{request.url.query}"
            login_url = frontend_url(
                "/admin/login", query=urlencode({"next": next_path})
            )
            return RedirectResponse(login_url, status_code=302)

        if inspect.iscoroutinefunction(view_func):
            return await view_func(*args, **kwargs)
        return view_func(*args, **kwargs)

    return wrapper


# 管理者セッションを検証し、未認可の場合は401エラーレスポンスを返す関数
# Validate the administrator session, returning a 401 JSONResponse on failure.
def _admin_guard(request: Request):
    if not request.session.get("is_admin"):
        return jsonify({"status": "fail", "error": "Unauthorized"}, status_code=401)
    return None


# リクエストからJSONまたはフォームデータを取得する関数
# Extract payload variables from either a JSON request body or multipart form fields.
async def _get_payload(request: Request) -> dict:
    data = await get_json(request)
    if data is not None:
        return data
    form = await request.form()
    return {key: value for key, value in form.items()}


# 管理者ログインページへリダイレクトするエンドポイント
# Route endpoint that redirects users to the administrator login view.
@admin_bp.api_route("/login", methods=["GET", "POST"], name="admin.login")
async def login(request: Request):
    status_code = 302 if request.method == "GET" else 303
    return redirect_to_frontend(request, path="/admin/login", status_code=status_code)


# 管理者ログインを検証し、セッションを確立するAPIエンドポイント
# API endpoint to verify administrator password credentials and rotate session identifiers.
@admin_bp.post("/api/login", name="admin.api_login")
async def api_login(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
):
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    payload = await _get_payload(request)
    password = payload.get("password") or ""
    next_url = sanitize_next_path(payload.get("next"), default="/admin")
    allowed, limit_error = consume_admin_login_limit(
        request,
        service=resolved_auth_limit_service,
    )
    if not allowed:
        return jsonify_rate_limited(
            limit_error or "試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=parse_retry_after_seconds(
                limit_error,
                default=DEFAULT_RETRY_AFTER_SECONDS,
            ),
            status="fail",
        )

    if _verify_admin_password(password):
        rotate_session_identifier(request)
        request.session["is_admin"] = True
        flash(request, "Logged in as administrator.", "success")
        redirect_url = frontend_url(next_url)
        return jsonify({"status": "success", "redirect": redirect_url})

    return jsonify({"status": "fail", "error": "Invalid password."}, status_code=401)


# 管理者セッションを破棄するAPIエンドポイント
# API endpoint to clear the administrator session state.
@admin_bp.post("/api/logout", name="admin.api_logout")
async def api_logout(request: Request):
    request.session.pop("is_admin", None)
    flash(request, "Logged out of administrator session.", "success")
    return jsonify(
        {"status": "success", "redirect": frontend_url("/admin/login")}
    )


# 管理者セッションを破棄してログイン画面にリダイレクトするエンドポイント
# Route endpoint to log out of the administrator session and redirect to login.
@admin_bp.get("/logout", name="admin.logout")
@admin_required
async def logout(request: Request):
    request.session.pop("is_admin", None)
    flash(request, "Logged out of administrator session.", "success")
    return RedirectResponse(frontend_url("/admin/login"), status_code=302)


# データベースに存在するユーザーテーブルの一覧を取得する関数
# Fetch the list of user base tables defined in the current database schema.
def _fetch_tables(cursor) -> list[str]:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    return [row[0] for row in cursor.fetchall()]


# テーブルのカラム詳細属性（型、ヌル許容、主キー/ユニーク等）を取得する関数
# Retrieve database column attributes (data type, nullability, indexing keys, default values).
def _fetch_table_columns(cursor, table_name: str) -> list[dict[str, object]]:
    cursor.execute(
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
        JOIN pg_catalog.pg_class rel
          ON rel.oid = attr.attrelid
        JOIN pg_catalog.pg_namespace nsp
          ON nsp.oid = rel.relnamespace
        LEFT JOIN pg_catalog.pg_attrdef def
          ON def.adrelid = attr.attrelid
         AND def.adnum = attr.attnum
        WHERE nsp.nspname = current_schema()
          AND rel.relname = %s
          AND attr.attnum > 0
          AND NOT attr.attisdropped
        ORDER BY attr.attnum
        """,
        (table_name,),
    )
    columns: list[dict[str, object]] = []
    for row in cursor.fetchall():
        columns.append(
            {
                "name": row[0],
                "type": row[1],
                "nullable": bool(row[2]),
                "key": row[3],
                "default": row[4],
                "extra": row[5],
            }
        )
    return columns


# テーブルデータのプレビュー（最大100件）を取得する関数
# Query the table to retrieve up to 100 rows of preview data.
def _fetch_table_preview(cursor, table_name: str) -> tuple[list[str], list[tuple]]:
    psql = _require_pg_sql()
    cursor.execute(
        psql.SQL("SELECT * FROM {} LIMIT 100").format(_sql_identifier(table_name))
    )
    rows = cursor.fetchall()
    column_names = [desc[0] for desc in cursor.description]
    return column_names, rows


# 安全にエスケープされたテーブル作成（CREATE TABLE）SQLクエリを組み立てる関数
# Construct a safely-escaped CREATE TABLE query utilizing psycopg2.sql.
def _build_create_table_sql(
    table_name: str, column_definitions: str, table_options: str = ""
):
    psql = _require_pg_sql()
    parsed_columns = _parse_column_definitions(column_definitions)
    validated_options = _validate_table_options(table_options)
    statement = psql.SQL("CREATE TABLE {} ({})").format(
        _sql_identifier(table_name),
        psql.SQL(", ").join(_build_column_sql(column) for column in parsed_columns),
    )
    if validated_options:
        statement = statement + psql.SQL(" ") + psql.SQL(validated_options)
    return statement


# 安全にエスケープされたテーブル削除（DROP TABLE）SQLクエリを組み立てる関数
# Construct a safely-escaped DROP TABLE query.
def _build_drop_table_sql(table_name: str):
    psql = _require_pg_sql()
    return psql.SQL("DROP TABLE {}").format(_sql_identifier(table_name))


# 安全にエスケープされたカラム追加（ALTER TABLE ADD COLUMN）SQLクエリを組み立てる関数
# Construct a safely-escaped ALTER TABLE ADD COLUMN query.
def _build_add_column_sql(table_name: str, column_name: str, column_type: str):
    psql = _require_pg_sql()
    parsed_definition = _parse_column_definition(f"{column_name} {column_type}")
    return psql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(
        _sql_identifier(table_name),
        _sql_identifier(str(parsed_definition["name"])),
        psql.SQL(
            " ".join(
                [str(parsed_definition["type"]), *[str(item) for item in parsed_definition["modifiers"]]]
            )
        ),
    )


# 安全にエスケープされたカラム削除（ALTER TABLE DROP COLUMN）SQLクエリを組み立てる関数
# Construct a safely-escaped ALTER TABLE DROP COLUMN query.
def _build_drop_column_sql(table_name: str, column_name: str):
    psql = _require_pg_sql()
    return psql.SQL("ALTER TABLE {} DROP COLUMN {}").format(
        _sql_identifier(table_name), _sql_identifier(column_name)
    )


# 管理用ダッシュボードに必要なテーブル一覧と選択テーブルの詳細データをDBからロードする関数
# Load all database tables metadata, column definitions, and row previews for the selected table.
def _load_dashboard_data(selected_table: Optional[str]) -> dict:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        tables = _fetch_tables(cursor)
        column_names: list[str] = []
        column_details: list[dict[str, object]] = []
        existing_columns: list[str] = []
        rows: list[tuple] = []
        missing_selected_table = False

        if selected_table:
            if _is_safe_sql_identifier(selected_table) and selected_table in tables:
                column_names, rows = _fetch_table_preview(cursor, selected_table)
                column_details = _fetch_table_columns(cursor, selected_table)
                existing_columns = [column["name"] for column in column_details]
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
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


# データベースにテーブルを新規作成する関数
# Execute CREATE TABLE in the database and commit the transaction.
def _create_table_in_db(table_name: str, column_definitions: str, table_options: str) -> None:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(_build_create_table_sql(table_name, column_definitions, table_options))
        connection.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


# 指定テーブルが存在する場合にそれを削除する関数
# Drop the table if it exists in the database schema and commit.
def _drop_table_if_exists(table_name: str) -> bool:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        existing_tables = _fetch_tables(cursor)
        if table_name not in existing_tables:
            return False
        cursor.execute(_build_drop_table_sql(table_name))
        connection.commit()
        return True
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


# テーブル名と重複をチェックした上でカラムを追加する関数
# Check table existence and duplicate column names before executing ALTER TABLE ADD COLUMN.
def _add_column_if_valid(table_name: str, column_name: str, column_type: str) -> str:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        tables = _fetch_tables(cursor)
        if table_name not in tables:
            return "missing_table"

        existing_columns = [column["name"] for column in _fetch_table_columns(cursor, table_name)]
        normalized_existing_columns = {name.lower() for name in existing_columns}
        if column_name.lower() in normalized_existing_columns:
            return "duplicate_column"

        cursor.execute(_build_add_column_sql(table_name, column_name, column_type))
        connection.commit()
        return "ok"
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


# テーブル内にカラムが2つ以上ある場合のみ安全にカラムを削除する関数
# Drop the specified column from the table if it exists and is not the last remaining column.
def _drop_column_if_valid(table_name: str, column_name: str) -> tuple[str, Optional[str]]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        tables = _fetch_tables(cursor)
        if table_name not in tables:
            return "missing_table", None

        columns = _fetch_table_columns(cursor, table_name)
        existing_columns = [column["name"] for column in columns]
        column_lookup = {name.lower(): name for name in existing_columns}
        target_column = column_lookup.get(column_name.lower())
        if target_column is None:
            return "missing_column", None

        if len(existing_columns) <= 1:
            return "last_column", None

        cursor.execute(_build_drop_column_sql(table_name, target_column))
        connection.commit()
        return "ok", target_column
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


# 管理用ダッシュボード（SPAのフロントエンド）へリダイレクトするエンドポイント
# Route endpoint to redirect requests to frontend dashboard client view.
@admin_bp.get("/", name="admin.dashboard")
@admin_required
async def dashboard(request: Request):
    return redirect_to_frontend(request)


# ダッシュボード表示に必要なメタデータ（テーブル一覧、カラム、プレビュー）を返すAPIエンドポイント
# API endpoint supplying metadata (tables, columns list, rows preview) for the administrator dashboard.
@admin_bp.get("/api/dashboard", name="admin.api_dashboard")
async def api_dashboard(request: Request):
    guard = _admin_guard(request)
    if guard is not None:
        return guard

    selected_table_raw = (request.query_params.get("table") or "").strip()
    selected_table: Optional[str] = selected_table_raw or None
    if selected_table is not None and not _is_safe_sql_identifier(selected_table):
        selected_table = None
        flash(request, "Invalid table selection.", "error")
    tables: list[str] = []
    column_names: list[str] = []
    column_details: list[dict[str, object]] = []
    existing_columns: list[str] = []
    rows: list[tuple] = []
    error: Optional[str] = None

    try:
        dashboard_data = await run_blocking(_load_dashboard_data, selected_table)
        tables = dashboard_data["tables"]
        selected_table = dashboard_data["selected_table"]
        column_names = dashboard_data["column_names"]
        column_details = dashboard_data["column_details"]
        existing_columns = dashboard_data["existing_columns"]
        rows = dashboard_data["rows"]
        if dashboard_data["missing_selected_table"]:
            flash(request, "The selected table does not exist.", "error")
    except Error:  # pragma: no cover - defensive logging
        logger.exception("Failed to load admin dashboard data.")
        error = "ダッシュボード情報の取得に失敗しました。"

    messages = get_flashed_messages(request, with_categories=True)

    return jsonify(
        {
            "tables": tables,
            "selected_table": selected_table,
            "column_names": column_names,
            "column_details": column_details,
            "existing_columns": existing_columns,
            "rows": rows,
            "error": error,
            "messages": messages,
        }
    )


# POSTフォームデータからテーブルを新規作成するエンドポイント（ダッシュボードへリダイレクト）
# Route endpoint to handle form posts for table creation, redirecting back to the dashboard.
@admin_bp.post("/create-table", name="admin.create_table")
@admin_required
async def create_table(request: Request):
    form = await request.form()
    table_name = form.get("table_name", "").strip()
    column_definitions = form.get("columns", "").strip()
    table_options = form.get("table_options", "").strip()

    if not table_name or not column_definitions:
        flash(request, "Table name and column definition are required.", "error")
        return RedirectResponse(frontend_admin_dashboard_url(request), status_code=302)

    if _has_multiple_statements(column_definitions):
        flash(request, "カラム定義に複数の文を含めることはできません。", "error")
        return RedirectResponse(frontend_admin_dashboard_url(request), status_code=302)

    try:
        table_name = _validate_sql_identifier(table_name, "table name")
        _parse_column_definitions(column_definitions)
        table_options = _validate_table_options(table_options)
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(frontend_admin_dashboard_url(request), status_code=302)

    try:
        await run_blocking(
            _create_table_in_db, table_name, column_definitions, table_options
        )
        flash(request, f"Table '{table_name}' created successfully.", "success")
    except ValueError as exc:
        flash(request, str(exc), "error")
    except Error:
        logger.exception("Failed to create table.")
        flash(request, "Failed to create table due to an internal error.", "error")

    return RedirectResponse(frontend_admin_dashboard_url(request), status_code=302)


# JSONデータからテーブルを新規作成するAPIエンドポイント
# API endpoint to handle JSON payloads for table creation.
@admin_bp.post("/api/create-table", name="admin.api_create_table")
async def api_create_table(request: Request):
    guard = _admin_guard(request)
    if guard is not None:
        return guard

    payload = await _get_payload(request)
    table_name = (payload.get("table_name") or "").strip()
    column_definitions = (payload.get("columns") or "").strip()
    table_options = (payload.get("table_options") or "").strip()

    if not table_name or not column_definitions:
        flash(request, "Table name and column definition are required.", "error")
        return jsonify(
            {"status": "fail", "error": "Table name and column definition are required."},
            status_code=400,
        )

    if _has_multiple_statements(column_definitions):
        flash(request, "カラム定義に複数の文を含めることはできません。", "error")
        return jsonify(
            {"status": "fail", "error": "Invalid column definition."}, status_code=400
        )

    try:
        table_name = _validate_sql_identifier(table_name, "table name")
        _parse_column_definitions(column_definitions)
        table_options = _validate_table_options(table_options)
    except ValueError as exc:
        flash(request, str(exc), "error")
        return jsonify({"status": "fail", "error": str(exc)}, status_code=400)

    try:
        await run_blocking(
            _create_table_in_db, table_name, column_definitions, table_options
        )
        flash(request, f"Table '{table_name}' created successfully.", "success")
        return jsonify({"status": "success", "redirect": frontend_admin_dashboard_url(request)})
    except ValueError as exc:
        flash(request, str(exc), "error")
        return jsonify({"status": "fail", "error": str(exc)}, status_code=400)
    except Error:
        flash(request, "Failed to create table due to an internal error.", "error")
        return log_and_internal_server_error(
            logger,
            "Admin API create-table failed.",
            status="fail",
        )


# POSTフォームデータから指定テーブルを削除するエンドポイント（ダッシュボードへリダイレクト）
# Route endpoint to handle form posts for deleting a table, redirecting back to the dashboard.
@admin_bp.post("/delete-table", name="admin.delete_table")
@admin_required
async def delete_table(request: Request):
    form = await request.form()
    table_name = form.get("table_name", "").strip()

    if not table_name:
        flash(request, "Table name is required for deletion.", "error")
        return RedirectResponse(frontend_admin_dashboard_url(request), status_code=302)

    try:
        table_name = _validate_sql_identifier(table_name, "table name")
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(frontend_admin_dashboard_url(request), status_code=302)

    try:
        deleted = await run_blocking(_drop_table_if_exists, table_name)
        if not deleted:
            flash(request, f"Table '{table_name}' does not exist.", "error")
            return RedirectResponse(frontend_admin_dashboard_url(request), status_code=302)
        flash(request, f"Table '{table_name}' deleted successfully.", "success")
    except Error:
        logger.exception("Failed to delete table.")
        flash(request, "Failed to delete table due to an internal error.", "error")

    return RedirectResponse(frontend_admin_dashboard_url(request), status_code=302)


# 指定テーブルを削除するAPIエンドポイント
# API endpoint to handle JSON payloads for deleting a table.
@admin_bp.post("/api/delete-table", name="admin.api_delete_table")
async def api_delete_table(request: Request):
    guard = _admin_guard(request)
    if guard is not None:
        return guard

    payload = await _get_payload(request)
    table_name = (payload.get("table_name") or "").strip()

    if not table_name:
        flash(request, "Table name is required for deletion.", "error")
        return jsonify(
            {"status": "fail", "error": "Table name is required."}, status_code=400
        )

    try:
        table_name = _validate_sql_identifier(table_name, "table name")
    except ValueError as exc:
        flash(request, str(exc), "error")
        return jsonify({"status": "fail", "error": str(exc)}, status_code=400)

    try:
        deleted = await run_blocking(_drop_table_if_exists, table_name)
        if not deleted:
            flash(request, f"Table '{table_name}' does not exist.", "error")
            return jsonify(
                {"status": "fail", "error": "Table does not exist."}, status_code=404
            )
        flash(request, f"Table '{table_name}' deleted successfully.", "success")
        return jsonify({"status": "success", "redirect": frontend_admin_dashboard_url(request)})
    except Error:
        flash(request, "Failed to delete table due to an internal error.", "error")
        return log_and_internal_server_error(
            logger,
            "Admin API delete-table failed.",
            status="fail",
        )


# POSTフォームデータからカラムを追加するエンドポイント（ダッシュボードへリダイレクト）
# Route endpoint to handle form posts for adding a column, redirecting back to the dashboard.
@admin_bp.post("/add-column", name="admin.add_column")
@admin_required
async def add_column(request: Request):
    form = await request.form()
    table_name = form.get("table_name", "").strip()
    column_name = form.get("column_name", "").strip()
    column_type = form.get("column_type", "").strip()

    if not table_name or not column_name or not column_type:
        flash(request, "テーブル名、カラム名、カラム定義は必須です。", "error")
        return RedirectResponse(
            frontend_admin_dashboard_url(request, table=table_name), status_code=302
        )

    if _has_multiple_statements(column_type):
        flash(request, "カラム定義に複数の文を含めることはできません。", "error")
        return RedirectResponse(
            frontend_admin_dashboard_url(request, table=table_name), status_code=302
        )

    try:
        table_name = _validate_sql_identifier(table_name, "table name")
        column_name = _validate_sql_identifier(column_name, "column name")
        _parse_column_definition(f"{column_name} {column_type}")
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(
            frontend_admin_dashboard_url(request, table=table_name), status_code=302
        )

    try:
        status = await run_blocking(_add_column_if_valid, table_name, column_name, column_type)
        if status == "missing_table":
            flash(request, f"テーブル '{table_name}' は存在しません。", "error")
            return RedirectResponse(frontend_admin_dashboard_url(request), status_code=302)
        if status == "duplicate_column":
            flash(request, f"カラム '{column_name}' は既に存在します。", "error")
            return RedirectResponse(
                frontend_admin_dashboard_url(request, table=table_name), status_code=302
            )
        flash(request, f"カラム '{column_name}' をテーブル '{table_name}' に追加しました。", "success")
    except Error:
        logger.exception("Failed to add column.")
        flash(request, "カラムの追加に失敗しました。内部エラーが発生しました。", "error")

    return RedirectResponse(
        frontend_admin_dashboard_url(request, table=table_name), status_code=302
    )


# カラムをテーブルに追加するAPIエンドポイント
# API endpoint to handle JSON payloads for adding a new column to a table.
@admin_bp.post("/api/add-column", name="admin.api_add_column")
async def api_add_column(request: Request):
    guard = _admin_guard(request)
    if guard is not None:
        return guard

    payload = await _get_payload(request)
    table_name = (payload.get("table_name") or "").strip()
    column_name = (payload.get("column_name") or "").strip()
    column_type = (payload.get("column_type") or "").strip()

    if not table_name or not column_name or not column_type:
        flash(request, "テーブル名、カラム名、カラム定義は必須です。", "error")
        return jsonify(
            {"status": "fail", "error": "Required fields are missing."}, status_code=400
        )

    if _has_multiple_statements(column_type):
        flash(request, "カラム定義に複数の文を含めることはできません。", "error")
        return jsonify(
            {"status": "fail", "error": "Invalid column definition."}, status_code=400
        )

    try:
        table_name = _validate_sql_identifier(table_name, "table name")
        column_name = _validate_sql_identifier(column_name, "column name")
        _parse_column_definition(f"{column_name} {column_type}")
    except ValueError as exc:
        flash(request, str(exc), "error")
        return jsonify({"status": "fail", "error": str(exc)}, status_code=400)

    try:
        status = await run_blocking(_add_column_if_valid, table_name, column_name, column_type)
        if status == "missing_table":
            flash(request, f"テーブル '{table_name}' は存在しません。", "error")
            return jsonify(
                {"status": "fail", "error": "Table does not exist."}, status_code=404
            )
        if status == "duplicate_column":
            flash(request, f"カラム '{column_name}' は既に存在します。", "error")
            return jsonify(
                {"status": "fail", "error": "Column already exists."}, status_code=400
            )
        flash(request, f"カラム '{column_name}' をテーブル '{table_name}' に追加しました。", "success")
        return jsonify(
            {
                "status": "success",
                "redirect": frontend_admin_dashboard_url(request, table=table_name),
            }
        )
    except Error:
        flash(request, "カラムの追加に失敗しました。内部エラーが発生しました。", "error")
        return log_and_internal_server_error(
            logger,
            "Admin API add-column failed.",
            status="fail",
        )


# POSTフォームデータからカラムを削除するエンドポイント（ダッシュボードへリダイレクト）
# Route endpoint to handle form posts for dropping a column, redirecting back to the dashboard.
@admin_bp.post("/delete-column", name="admin.delete_column")
@admin_required
async def delete_column(request: Request):
    form = await request.form()
    table_name = form.get("table_name", "").strip()
    column_name = form.get("column_name", "").strip()

    if not table_name or not column_name:
        flash(request, "テーブル名とカラム名は必須です。", "error")
        return RedirectResponse(
            frontend_admin_dashboard_url(request, table=table_name), status_code=302
        )

    try:
        table_name = _validate_sql_identifier(table_name, "table name")
        column_name = _validate_sql_identifier(column_name, "column name")
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(
            frontend_admin_dashboard_url(request, table=table_name), status_code=302
        )

    try:
        status, target_column = await run_blocking(
            _drop_column_if_valid, table_name, column_name
        )
        if status == "missing_table":
            flash(request, f"テーブル '{table_name}' は存在しません。", "error")
            return RedirectResponse(frontend_admin_dashboard_url(request), status_code=302)
        if status == "missing_column":
            flash(request, f"カラム '{column_name}' は存在しません。", "error")
            return RedirectResponse(
                frontend_admin_dashboard_url(request, table=table_name), status_code=302
            )
        if status == "last_column":
            flash(request, "テーブルには少なくとも1つのカラムが必要です。", "error")
            return RedirectResponse(
                frontend_admin_dashboard_url(request, table=table_name), status_code=302
            )
        if status != "ok" or target_column is None:
            flash(request, "カラムの削除に失敗しました。", "error")
            return RedirectResponse(
                frontend_admin_dashboard_url(request, table=table_name), status_code=302
            )
        flash(request, f"カラム '{target_column}' をテーブル '{table_name}' から削除しました。", "success")
    except Error:
        logger.exception("Failed to delete column.")
        flash(request, "カラムの削除に失敗しました。内部エラーが発生しました。", "error")

    return RedirectResponse(
        frontend_admin_dashboard_url(request, table=table_name), status_code=302
    )


# カラムをテーブルから削除するAPIエンドポイント
# API endpoint to handle JSON payloads for dropping a column from a table.
@admin_bp.post("/api/delete-column", name="admin.api_delete_column")
async def api_delete_column(request: Request):
    guard = _admin_guard(request)
    if guard is not None:
        return guard

    payload = await _get_payload(request)
    table_name = (payload.get("table_name") or "").strip()
    column_name = (payload.get("column_name") or "").strip()

    if not table_name or not column_name:
        flash(request, "テーブル名とカラム名は必須です。", "error")
        return jsonify(
            {"status": "fail", "error": "Required fields are missing."}, status_code=400
        )

    try:
        table_name = _validate_sql_identifier(table_name, "table name")
        column_name = _validate_sql_identifier(column_name, "column name")
    except ValueError as exc:
        flash(request, str(exc), "error")
        return jsonify({"status": "fail", "error": str(exc)}, status_code=400)

    try:
        status, target_column = await run_blocking(
            _drop_column_if_valid, table_name, column_name
        )
        if status == "missing_table":
            flash(request, f"テーブル '{table_name}' は存在しません。", "error")
            return jsonify(
                {"status": "fail", "error": "Table does not exist."}, status_code=404
            )
        if status == "missing_column":
            flash(request, f"カラム '{column_name}' は存在しません。", "error")
            return jsonify(
                {"status": "fail", "error": "Column does not exist."}, status_code=404
            )
        if status == "last_column":
            flash(request, "テーブルには少なくとも1つのカラムが必要です。", "error")
            return jsonify(
                {"status": "fail", "error": "Cannot delete the last column."}, status_code=400
            )
        if status != "ok" or target_column is None:
            flash(request, "カラムの削除に失敗しました。", "error")
            return jsonify({"status": "fail", "error": "Column deletion failed."}, status_code=500)
        flash(
            request,
            f"カラム '{target_column}' をテーブル '{table_name}' から削除しました。",
            "success",
        )
        return jsonify(
            {
                "status": "success",
                "redirect": frontend_admin_dashboard_url(request, table=table_name),
            }
        )
    except Error:
        flash(request, "カラムの削除に失敗しました。内部エラーが発生しました。", "error")
        return log_and_internal_server_error(
            logger,
            "Admin API delete-column failed.",
            status="fail",
        )
