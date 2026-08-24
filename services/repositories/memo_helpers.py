from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any


def ensure_title(ai_response: str, provided_title: str) -> str:
    """
    メモのタイトルを保証する関数。空の場合はAIレスポンスの先頭行から抽出する。
    Ensure that a memo has a title. If not provided, extract the first non-empty line from the AI response.

    Args:
        ai_response (str): AIからの回答テキスト / The AI response text.
        provided_title (str): ユーザーが指定したタイトル / The title provided by the user.

    Returns:
        str: 決定されたタイトル（最大255文字） / The resolved title (max 255 characters).
    """
    # 左右の空白を取り除く
    # Strip whitespace from the provided title.
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


def user_id_from_session(session: dict[str, Any]) -> int | None:
    """
    セッションからユーザーIDを安全に取得する関数
    Safely extract and validate the user ID from the session.

    Args:
        session (dict[str, Any]): セッション辞書 / The session dictionary.

    Returns:
        int | None: 有効なユーザーID。無効または未設定の場合は None / Valid user ID or None if invalid or not set.
    """
    user_id = session.get("user_id")

    # user_id が整数型である場合のみ有効として返却
    # Return user_id only if it is of type int.
    if isinstance(user_id, int):
        return user_id
    return None


def parse_memo_text(raw: str | None) -> str:
    """
    メモの生テキストデータをパースする関数
    Safely parse raw memo text, resolving potential JSON strings.

    Args:
        raw (str | None): 生テキストデータ（JSON形式の文字列である可能性あり） / Raw text data (potentially a JSON-encoded string).

    Returns:
        str: パースされた平文テキスト / The parsed plain text.
    """
    if not raw:
        return ""

    # JSON文字列の場合があるのでデコードを試みる
    # Try to decode the string in case it is stored as a JSON string.
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            return parsed
    except (TypeError, ValueError):
        # JSONではない、またはパースエラーの場合はそのまま文字列として処理
        # If it is not JSON or parsing fails, fall back to the raw string.
        pass
    return raw


def parse_date_filter(raw: str) -> date | None:
    """
    日付フィルター文字列を date オブジェクトに変換する関数
    Parse an ISO date filter string into a date object.

    Args:
        raw (str): YYYY-MM-DD 形式の日付文字列 / An ISO date string format (YYYY-MM-DD).

    Returns:
        date | None: パースされた date オブジェクト。無効な形式の場合は None / The parsed date object, or None if invalid.
    """
    normalized = raw.strip()
    if not normalized:
        return None

    # ISOフォーマット (YYYY-MM-DD) からの変換を試みる
    # Attempt to parse from ISO format (YYYY-MM-DD).
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        # パースに失敗した場合はNoneを返す
        # Return None if parsing fails.
        return None


def date_start(raw: str) -> datetime | None:
    """
    指定日付の開始時刻（00:00:00）の datetime を取得する関数
    Get the start of the day (00:00:00) datetime for a given date string.

    Args:
        raw (str): YYYY-MM-DD 形式の日付文字列 / An ISO date string format (YYYY-MM-DD).

    Returns:
        datetime | None: 開始時刻の datetime、無効な場合は None / The start of day datetime, or None if invalid.
    """
    parsed = parse_date_filter(raw)
    if parsed is None:
        return None

    # 最小時刻（00:00:00）と結合して datetime を生成
    # Combine the parsed date with the minimum time of the day.
    return datetime.combine(parsed, time.min)


def date_end(raw: str) -> datetime | None:
    """
    指定日付の終了時刻（23:59:59.999999）の datetime を取得する関数
    Get the end of the day (23:59:59.999999) datetime for a given date string.

    Args:
        raw (str): YYYY-MM-DD 形式の日付文字列 / An ISO date string format (YYYY-MM-DD).

    Returns:
        datetime | None: 終了時刻의 datetime、無効な場合は None / The end of day datetime, or None if invalid.
    """
    parsed = parse_date_filter(raw)
    if parsed is None:
        return None

    # 最大時刻（23:59:59.999999）と結合して datetime を生成
    # Combine the parsed date with the maximum time of the day.
    return datetime.combine(parsed, time.max)


def resolve_sort_order(sort: str) -> str:
    """
    指定されたソート条件に応じたSQLのORDER BY句を解決する関数
    Resolve the SQL ORDER BY fragment based on the specified sort option.

    Args:
        sort (str): ソートキー ("manual", "oldest", "updated", "title" など) / The sort key.

    Returns:
        str: SQL用の ORDER BY 部分文字列 / The SQL ORDER BY fragment.
    """
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
