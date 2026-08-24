from __future__ import annotations

import csv
import io
import json
from typing import Any

from services.datetime_serialization import serialize_datetime_iso
from services.repositories.memo_helpers import parse_memo_text


def build_markdown_export(memos: list[dict[str, Any]]) -> str:
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
    result = [
        {
            "id": memo.get("id"),
            "title": memo.get("title") or "保存したメモ",
            "ai_response": parse_memo_text(memo.get("ai_response")),
            "background_color": memo.get("background_color"),
            "created_at": serialize_datetime_iso(memo.get("created_at")),
            "updated_at": serialize_datetime_iso(memo.get("updated_at")),
        }
        for memo in memos
    ]
    return json.dumps(result, ensure_ascii=False, indent=2)


def build_csv_export(memos: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "title", "ai_response", "background_color", "created_at", "updated_at"])
    for memo in memos:
        writer.writerow(
            [
                memo.get("id", ""),
                memo.get("title") or "保存したメモ",
                parse_memo_text(memo.get("ai_response")),
                memo.get("background_color") or "",
                serialize_datetime_iso(memo.get("created_at")) or "",
                serialize_datetime_iso(memo.get("updated_at")) or "",
            ]
        )
    return output.getvalue()
