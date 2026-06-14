from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any


# メモのタイトルを保証する関数。空の場合はAIレスポンスの先頭行から抽出する。
# Ensure that a memo has a title. If not provided, extract the first non-empty line from the AI response.
def ensure_title(ai_response: str, provided_title: str) -> str:
    title = provided_title.strip()
    # タイトルが指定されている場合は、最大255文字に制限して返す
    # If a title is provided, return it limited to a maximum of 255 characters.
    if title:
        return title[:255]
    # 指定されていない場合、AIレスポンスから最初の非空行をタイトルとして採用する
    # If not provided, use the first non-empty line of the AI response as the title.
    for line in ai_response.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:255]
    # 代替のデフォルトタイトル
    # Fallback default title.
    return "新しいメモ"


# セッションからユーザーIDを安全に取得する関数
# Safely extract and validate the user ID from the session.
def user_id_from_session(session: dict[str, Any]) -> int | None:
    user_id = session.get("user_id")
    # user_id が整数型である場合のみ有効として返却
    # Return user_id only if it is of type int.
    if isinstance(user_id, int):
        return user_id
    return None


# メモの生テキストデータをパースする関数
# Safely parse raw memo text, resolving potential JSON strings.
def parse_memo_text(raw: str | None) -> str:
    if not raw:
        return ""
    # JSON文字列の場合があるのでデコードを試みる
    # Try to decode the string in case it is stored as a JSON string.
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            return parsed
    except (TypeError, ValueError):
        pass
    return raw


# 日付フィルター文字列を date オブジェクトに変換する関数
# Parse an ISO date filter string into a date object.
def parse_date_filter(raw: str) -> date | None:
    normalized = raw.strip()
    if not normalized:
        return None
    # ISOフォーマット (YYYY-MM-DD) からの変換を試みる
    # Attempt to parse from ISO format (YYYY-MM-DD).
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


# 指定日付の開始時刻（00:00:00）の datetime を取得する関数
# Get the start of the day (00:00:00) datetime for a given date string.
def date_start(raw: str) -> datetime | None:
    parsed = parse_date_filter(raw)
    if parsed is None:
        return None
    # 最小時刻（00:00:00）と結合して datetime を生成
    # Combine the parsed date with the minimum time of the day.
    return datetime.combine(parsed, time.min)


# 指定日付の終了時刻（23:59:59.999999）の datetime を取得する関数
# Get the end of the day (23:59:59.999999) datetime for a given date string.
def date_end(raw: str) -> datetime | None:
    parsed = parse_date_filter(raw)
    if parsed is None:
        return None
    # 最大時刻（23:59:59.999999）と結合して datetime を生成
    # Combine the parsed date with the maximum time of the day.
    return datetime.combine(parsed, time.max)


# 指定されたソート条件に応じたSQLのORDER BY句を解決する関数
# Resolve the SQL ORDER BY fragment based on the specified sort option.
def resolve_sort_order(sort: str) -> str:
    # 手動並び替えの場合は sort_order カラムを優先（NULLの場合は作成日のエポック値を代替）
    # For manual sorting, prioritize sort_order column (fallback to created_at epoch if NULL).
    if sort == "manual":
        return "COALESCE(me.sort_order, EXTRACT(EPOCH FROM me.created_at)::numeric) DESC, me.created_at DESC"
    # 古い順
    # Oldest first.
    if sort == "oldest":
        return "me.created_at ASC"
    # 更新日時が新しい順
    # Recently updated first.
    if sort == "updated":
        return "me.updated_at DESC"
    # タイトルのアルファベット/五十音順
    # Alphabetical order of title.
    if sort == "title":
        return "LOWER(me.title) ASC, me.created_at DESC"
    # デフォルトは作成日の新しい順
    # Default: newest created first.
    return "me.created_at DESC"
