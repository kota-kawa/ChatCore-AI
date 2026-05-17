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
    memo_module = sys.modules.get("blueprints.memo")
    if memo_module is not None:
        return getattr(memo_module, "get_db_connection", default_get_db_connection)()
    return default_get_db_connection()


def fetch_memos_for_export(
    user_id: int,
    memo_ids: list[int] | None,
) -> list[dict[str, Any]]:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor(dictionary=True)
        if memo_ids:
            placeholders = ",".join(["%s"] * len(memo_ids))
            cursor.execute(
                f"""
                SELECT id, title, ai_response, created_at, updated_at
                FROM memo_entries
                WHERE user_id = %s AND id IN ({placeholders})
                ORDER BY created_at DESC
                """,
                tuple([user_id, *memo_ids]),
            )
        else:
            cursor.execute(
                """
                SELECT id, title, ai_response, created_at, updated_at
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
    parts: list[str] = ["# メモエクスポート\n"]
    for memo in memos:
        title = memo.get("title") or "保存したメモ"
        created = serialize_datetime_iso(memo.get("created_at")) or ""
        ai_resp = parse_memo_text(memo.get("ai_response"))

        parts.append(f"## {title}\n")
        if created:
            parts.append(f"**作成日時:** {created}\n")
        if ai_resp:
            parts.append(f"\n### AIの回答\n\n{ai_resp}\n")
        parts.append("\n---\n\n")
    return "\n".join(parts)


def build_json_export(memos: list[dict[str, Any]]) -> str:
    result = []
    for memo in memos:
        result.append({
            "id": memo.get("id"),
            "title": memo.get("title") or "保存したメモ",
            "ai_response": parse_memo_text(memo.get("ai_response")),
            "created_at": serialize_datetime_iso(memo.get("created_at")),
            "updated_at": serialize_datetime_iso(memo.get("updated_at")),
        })
    return json.dumps(result, ensure_ascii=False, indent=2)


def build_csv_export(memos: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "title", "ai_response", "created_at", "updated_at"])
    for memo in memos:
        writer.writerow([
            memo.get("id", ""),
            memo.get("title") or "保存したメモ",
            parse_memo_text(memo.get("ai_response")),
            serialize_datetime_iso(memo.get("created_at")) or "",
            serialize_datetime_iso(memo.get("updated_at")) or "",
        ])
    return output.getvalue()
