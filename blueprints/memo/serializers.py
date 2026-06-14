from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from services.datetime_serialization import serialize_datetime_iso
from services.web import frontend_url as default_frontend_url

from .constants import DEFAULT_EXCERPT_LENGTH
from .helpers import parse_memo_text


def _frontend_url(path: str) -> str:
    """
    パスからフロントエンドのURLを解決するヘルパー関数
    Helper function to resolve the frontend URL from a given path.

    Args:
        path (str): リダイレクト先のパス / The target path for redirection.

    Returns:
        str: 完全修飾ドメイン名を含むURL / The fully qualified URL.
    """
    # メモモジュールのカスタムURL解決関数があれば使用し、無ければデフォルトを使用
    # Use the memo module's custom URL resolver if defined; otherwise, fallback to the default.
    memo_module = sys.modules.get("blueprints.memo")
    if memo_module is not None:
        # カスタムURL解決関数が存在する場合はそれを取得して呼び出す。存在しない場合はデフォルトの解決関数を使用
        # Get and call the custom URL resolver if it exists. Otherwise, use the default resolver.
        return getattr(memo_module, "frontend_url", default_frontend_url)(path)
    # モジュールが見つからない場合はデフォルトの解決関数を使用
    # Use the default resolver if the module is not found.
    return default_frontend_url(path)


def is_expired(expires_at: Any) -> bool:
    """
    有効期限が切れているか判定する関数
    Determine whether the expiration datetime has passed.

    Args:
        expires_at (Any): 判定対象の有効期限 / The expiration datetime to check.

    Returns:
        bool: 期限切れの場合はTrue、それ以外はFalse / True if expired, False otherwise.
    """
    # 期限が datetime 型でない場合は未期限とみなす
    # If the expiration date is not a datetime object, consider it not expired.
    if not isinstance(expires_at, datetime):
        return False
    # 現在のUTC時刻と比較して期限切れ判定。現在のUTC時間以前であればTrue
    # Compare with the current UTC datetime to check expiration. Returns True if current UTC is past or equal to expires_at.
    return expires_at <= datetime.utcnow()


def serialize_share_meta(memo: dict[str, Any]) -> dict[str, Any]:
    """
    メモの共有メタデータをシリアライズする関数
    Serialize the sharing metadata of a memo.

    Args:
        memo (dict[str, Any]): メモのレコードデータ / The memo record dictionary.

    Returns:
        dict[str, Any]: シリアライズされた共有メタデータ / The serialized sharing metadata.
    """
    # メモ情報から共有トークン、有効期限、無効化日時を取得
    # Retrieve the share token, expiration datetime, and revocation datetime from the memo dictionary.
    share_token = memo.get("share_token") or ""
    expires_at = memo.get("expires_at")
    revoked_at = memo.get("revoked_at")

    # トークンが存在し、無効化されておらず、有効期限内である場合にアクティブと判定
    # Considered active if token exists, is not revoked, and is not expired.
    is_active = bool(share_token) and revoked_at is None and not is_expired(expires_at)

    # シリアライズされた共有メタデータ情報を返す
    # Return the serialized sharing metadata.
    return {
        "share_token": share_token,
        "expires_at": serialize_datetime_iso(expires_at),
        "revoked_at": serialize_datetime_iso(revoked_at),
        "is_expired": is_expired(expires_at),
        "is_revoked": revoked_at is not None,
        "is_active": is_active,
        # アクティブな場合のみ共有URLを構築
        # Build the share URL only if the sharing state is active.
        "share_url": _frontend_url(f"/shared/memo/{share_token}") if is_active else "",
    }


def serialize_memo_summary(memo: dict[str, Any]) -> dict[str, Any]:
    """
    メモの概要情報をシリアライズする関数（一覧表示用）
    Serialize summary details of a memo (for list views).

    Args:
        memo (dict[str, Any]): メモのレコードデータ / The memo record dictionary.

    Returns:
        dict[str, Any]: 一覧表示用のシリアライズされたメモ概要情報 / The serialized memo summary.
    """
    # メモ本文からテキスト部分を抽出してプレビュー用にパース
    # Parse the memo text structure to extract preview text.
    preview_source = parse_memo_text(memo.get("preview_response") or "")

    # 共有メタデータをシリアライズ
    # Serialize the sharing metadata of this memo.
    share_meta = serialize_share_meta(memo)

    # 一覧表示に必要な属性をマッピングして返す
    # Map and return the attributes required for list representation.
    return {
        "id": memo.get("id"),
        "title": memo.get("title") or "保存したメモ",
        "created_at": serialize_datetime_iso(memo.get("created_at")),
        "updated_at": serialize_datetime_iso(memo.get("updated_at")),
        "archived_at": serialize_datetime_iso(memo.get("archived_at")),
        "pinned_at": serialize_datetime_iso(memo.get("pinned_at")),
        "is_archived": memo.get("archived_at") is not None,
        "is_pinned": memo.get("pinned_at") is not None,
        # 本文の抜粋を指定の長さで切り出し
        # Extract a preview excerpt up to the configured limit.
        "excerpt": preview_source[:DEFAULT_EXCERPT_LENGTH],
        "collection_id": memo.get("collection_id"),
        "collection_name": memo.get("collection_name"),
        "collection_color": memo.get("collection_color"),
        "background_color": memo.get("background_color"),
        **share_meta,
    }


def serialize_memo_detail(memo: dict[str, Any]) -> dict[str, Any]:
    """
    メモの詳細情報をシリアライズする関数
    Serialize full details of a memo.

    Args:
        memo (dict[str, Any]): メモのレコードデータ / The memo record dictionary.

    Returns:
        dict[str, Any]: 詳細表示用のシリアライズされたメモ情報 / The serialized memo details.
    """
    # 共有メタデータをシリアライズ
    # Serialize sharing metadata.
    share_meta = serialize_share_meta(memo)

    # 詳細表示に必要な属性（AIの回答を含む）をマッピングして返す
    # Map and return all attributes required for detail view (including the AI response).
    return {
        "id": memo.get("id"),
        "title": memo.get("title") or "保存したメモ",
        "created_at": serialize_datetime_iso(memo.get("created_at")),
        "updated_at": serialize_datetime_iso(memo.get("updated_at")),
        "archived_at": serialize_datetime_iso(memo.get("archived_at")),
        "pinned_at": serialize_datetime_iso(memo.get("pinned_at")),
        "is_archived": memo.get("archived_at") is not None,
        "is_pinned": memo.get("pinned_at") is not None,
        "ai_response": memo.get("ai_response") or "",
        "collection_id": memo.get("collection_id"),
        "collection_name": memo.get("collection_name"),
        "collection_color": memo.get("collection_color"),
        "background_color": memo.get("background_color"),
        **share_meta,
    }


def share_payload(share_state: dict[str, Any]) -> dict[str, Any]:
    """
    共有状態を表すレスポンス用ペイロードを作成する関数
    Construct the response payload for a memo sharing state.

    Args:
        share_state (dict[str, Any]): 共有状態データ / The sharing state dictionary.

    Returns:
        dict[str, Any]: 構築された共有ペイロード / The constructed sharing payload dictionary.
    """
    # トークンを文字列にキャスト
    # Cast the token to string.
    share_token = str(share_state.get("share_token") or "")
    share_url = ""

    # 有効なトークンがあり、共有状態がアクティブであれば共有URLを設定
    # Set the share URL if the token is present and the share state is active.
    if share_token and bool(share_state.get("is_active")):
        share_url = _frontend_url(f"/shared/memo/{share_token}")

    # レスポンス用のディクショナリを返却
    # Return the response payload dictionary.
    return {"status": "success", **share_state, "share_url": share_url}
