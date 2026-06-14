from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any


# 日本語: ensure title の保証処理を担当します。
# English: Handle ensuring for ensure title.
def ensure_title(ai_response: str, provided_title: str) -> str:
    title = provided_title.strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if title:
        return title[:255]
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for line in ai_response.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:255]
    return "新しいメモ"


# 日本語: user id from session に関する処理の入口です。
# English: Entry point for logic related to user id from session.
def user_id_from_session(session: dict[str, Any]) -> int | None:
    user_id = session.get("user_id")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(user_id, int):
        return user_id
    return None


# 日本語: parse memo text の解析処理を担当します。
# English: Handle parsing for parse memo text.
def parse_memo_text(raw: str | None) -> str:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not raw:
        return ""
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            return parsed
    except (TypeError, ValueError):
        pass
    return raw


# 日本語: parse date filter の解析処理を担当します。
# English: Handle parsing for parse date filter.
def parse_date_filter(raw: str) -> date | None:
    normalized = raw.strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not normalized:
        return None
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


# 日本語: date start に関する処理の入口です。
# English: Entry point for logic related to date start.
def date_start(raw: str) -> datetime | None:
    parsed = parse_date_filter(raw)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if parsed is None:
        return None
    return datetime.combine(parsed, time.min)


# 日本語: date end に関する処理の入口です。
# English: Entry point for logic related to date end.
def date_end(raw: str) -> datetime | None:
    parsed = parse_date_filter(raw)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if parsed is None:
        return None
    return datetime.combine(parsed, time.max)


# 日本語: resolve sort order に関する処理の入口です。
# English: Entry point for logic related to resolve sort order.
def resolve_sort_order(sort: str) -> str:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if sort == "manual":
        return "COALESCE(me.sort_order, EXTRACT(EPOCH FROM me.created_at)::numeric) DESC, me.created_at DESC"
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if sort == "oldest":
        return "me.created_at ASC"
    if sort == "updated":
        return "me.updated_at DESC"
    if sort == "title":
        return "LOWER(me.title) ASC, me.created_at DESC"
    return "me.created_at DESC"
