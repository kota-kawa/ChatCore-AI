from __future__ import annotations

import csv
import io
import json
import sys
from typing import Any

from services.datetime_serialization import serialize_datetime_iso
from services.db import get_db_connection as default_get_db_connection

from .helpers import parse_memo_text


# 日本語: get db connection の取得処理を担当します。
# English: Handle fetching for get db connection.
def _get_db_connection():
    memo_module = sys.modules.get("blueprints.memo")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if memo_module is not None:
        return getattr(memo_module, "get_db_connection", default_get_db_connection)()
    return default_get_db_connection()


# 日本語: fetch memos for export の取得処理を担当します。
# English: Handle fetching for fetch memos for export.
def fetch_memos_for_export(
    user_id: int,
    memo_ids: list[int] | None,
) -> list[dict[str, Any]]:
    connection = None
    cursor = None
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        connection = _get_db_connection()
        cursor = connection.cursor(dictionary=True)
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


# 日本語: build markdown export の組み立て処理を担当します。
# English: Handle building for build markdown export.
def build_markdown_export(memos: list[dict[str, Any]]) -> str:
    parts: list[str] = ["# メモエクスポート\n"]
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
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


# 日本語: build json export の組み立て処理を担当します。
# English: Handle building for build json export.
def build_json_export(memos: list[dict[str, Any]]) -> str:
    result = []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
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


# 日本語: build csv export の組み立て処理を担当します。
# English: Handle building for build csv export.
def build_csv_export(memos: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "title", "ai_response", "background_color", "created_at", "updated_at"])
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for memo in memos:
        writer.writerow([
            memo.get("id", ""),
            memo.get("title") or "保存したメモ",
            parse_memo_text(memo.get("ai_response")),
            memo.get("background_color") or "",
            serialize_datetime_iso(memo.get("created_at")) or "",
            serialize_datetime_iso(memo.get("updated_at")) or "",
        ])
    return output.getvalue()
