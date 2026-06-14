from __future__ import annotations

import csv
import io
import json
import sys
from typing import Any

from services.datetime_serialization import serialize_datetime_iso
from services.db import get_db_connection as default_get_db_connection

from .helpers import parse_memo_text


def _get_db_connection():
    """
    メモモジュールから動的にDB接続取得関数を解決するヘルパー（循環参照防止）
    Helper to dynamically retrieve the DB connection function to avoid circular imports.

    Returns:
        Connection: データベース接続オブジェクト / The database connection object.
    """
    memo_module = sys.modules.get("blueprints.memo")
    if memo_module is not None:
        return getattr(memo_module, "get_db_connection", default_get_db_connection)()
    return default_get_db_connection()


def fetch_memos_for_export(
    user_id: int,
    memo_ids: list[int] | None,
) -> list[dict[str, Any]]:
    """
    エクスポート対象となるメモデータをデータベースから取得する関数
    Fetch memo entries from the database to prepare for export.

    Args:
        user_id (int): ユーザーID / User ID.
        memo_ids (list[int] | None): 取得対象のメモIDリスト（Noneの場合は全件） / Optional list of target memo IDs to retrieve.

    Returns:
        list[dict[str, Any]]: 取得したメモレコードのリスト / List of retrieved memo record dictionaries.
    """
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor(dictionary=True)
        # 特定のメモID一覧が指定されている場合はそれを取得、指定されていない場合は全メモ（上限1000件）を取得
        # If specific memo IDs are specified, query them; otherwise, query all user's memos (up to 1000).
        if memo_ids:
            placeholders = ",".join(["%s"] * len(memo_ids))
            cursor.execute(
                f"""
                SELECT id, title, ai_response, background_color, created_at, updated_at
                FROM memo_entries
                WHERE user_id = %s AND id IN ({placeholders})
                ORDER BY created_at DESC
                """,
                tuple([user_id, *memo_ids]),
            )
        else:
            cursor.execute(
                """
                SELECT id, title, ai_response, background_color, created_at, updated_at
                FROM memo_entries
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1000
                """,
                (user_id,),
            )
        return list(cursor.fetchall())
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def build_markdown_export(memos: list[dict[str, Any]]) -> str:
    """
    メモ一覧を Markdown 形式のドキュメントテキストにビルドする関数
    Construct a Markdown document from a list of memos.

    Args:
        memos (list[dict[str, Any]]): メモデータのリスト / List of memo dictionaries.

    Returns:
        str: 構築された Markdown テキスト / The constructed Markdown document string.
    """
    parts: list[str] = ["# メモエクスポート\n"]
    for memo in memos:
        title = memo.get("title") or "保存したメモ"
        created = serialize_datetime_iso(memo.get("created_at")) or ""
        ai_resp = parse_memo_text(memo.get("ai_response"))

        parts.append(f"## {title}\n")
        if created:
            parts.append(f"**作成日時:** {created}\n")
        if memo.get("background_color"):
            parts.append(f"**背景色:** {memo.get('background_color')}\n")
        if ai_resp:
            parts.append(f"\n### 本文\n\n{ai_resp}\n")
        parts.append("\n---\n\n")
    return "\n".join(parts)


def build_json_export(memos: list[dict[str, Any]]) -> str:
    """
    メモ一覧を JSON 形式の文字列にビルドする関数
    Construct a JSON string representing the list of memos.

    Args:
        memos (list[dict[str, Any]]): メモデータのリスト / List of memo dictionaries.

    Returns:
        str: 構築された JSON 文字列 / The constructed JSON string.
    """
    result = []
    for memo in memos:
        result.append({
            "id": memo.get("id"),
            "title": memo.get("title") or "保存したメモ",
            "ai_response": parse_memo_text(memo.get("ai_response")),
            "background_color": memo.get("background_color"),
            "created_at": serialize_datetime_iso(memo.get("created_at")),
            "updated_at": serialize_datetime_iso(memo.get("updated_at")),
        })
    return json.dumps(result, ensure_ascii=False, indent=2)


def build_csv_export(memos: list[dict[str, Any]]) -> str:
    """
    メモ一覧を CSV 形式の文字列にビルドする関数
    Construct a CSV formatted string from the list of memos.

    Args:
        memos (list[dict[str, Any]]): メモデータのリスト / List of memo dictionaries.

    Returns:
        str: 構築された CSV 文字列 / The constructed CSV string.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    # ヘッダー行を出力
    # Write header row.
    writer.writerow(["id", "title", "ai_response", "background_color", "created_at", "updated_at"])
    for memo in memos:
        # メモデータ行を出力
        # Write memo record row.
        writer.writerow([
            memo.get("id", ""),
            memo.get("title") or "保存したメモ",
            parse_memo_text(memo.get("ai_response")),
            memo.get("background_color") or "",
            serialize_datetime_iso(memo.get("created_at")) or "",
            serialize_datetime_iso(memo.get("updated_at")) or "",
        ])
    return output.getvalue()
