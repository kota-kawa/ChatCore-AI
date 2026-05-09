from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any


def ensure_title(ai_response: str, provided_title: str) -> str:
    title = provided_title.strip()
    if title:
        return title[:255]
    for line in ai_response.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:255]
    return "新しいメモ"


def user_id_from_session(session: dict[str, Any]) -> int | None:
    user_id = session.get("user_id")
    if isinstance(user_id, int):
        return user_id
    return None


def parse_memo_text(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            return parsed
    except (TypeError, ValueError):
        pass
    return raw


def parse_date_filter(raw: str) -> date | None:
    normalized = raw.strip()
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def date_start(raw: str) -> datetime | None:
    parsed = parse_date_filter(raw)
    if parsed is None:
        return None
    return datetime.combine(parsed, time.min)


def date_end(raw: str) -> datetime | None:
    parsed = parse_date_filter(raw)
    if parsed is None:
        return None
    return datetime.combine(parsed, time.max)


def resolve_sort_order(sort: str) -> str:
    if sort == "oldest":
        return "me.created_at ASC"
    if sort == "updated":
        return "me.updated_at DESC"
    if sort == "title":
        return "LOWER(me.title) ASC, me.created_at DESC"
    return "me.created_at DESC"
