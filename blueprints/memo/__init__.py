from __future__ import annotations

from typing import Any

from services.db import get_db_connection
from services.memo_ai import embeddings_available, generate_embedding, suggest_title
from services.memo_share import (
    create_or_get_shared_memo_token,
    get_memo_share_state,
    get_shared_memo_payload,
    revoke_shared_memo_token,
)
from services.web import frontend_url

from .embeddings import schedule_embedding as _schedule_embedding
from .exports import (
    build_csv_export as _build_csv_export,
    build_json_export as _build_json_export,
    build_markdown_export as _build_markdown_export,
    fetch_memos_for_export as _fetch_memos_for_export,
)
from .helpers import ensure_title as _ensure_title
from .repository import (
    bulk_action as _bulk_action,
    delete_collection as _delete_collection,
    delete_memo as _delete_memo,
    fetch_collections as _fetch_collections,
    fetch_memo_detail as _fetch_memo_detail,
    fetch_memo_summaries as _fetch_memo_summaries,
    insert_collection as _insert_collection,
    insert_memo as _insert_memo,
    set_memo_archive_state as _set_memo_archive_state,
    set_memo_pin_state as _set_memo_pin_state,
    update_collection as _update_collection,
    update_memo as _update_memo,
)
from .routes import (
    api_archive_memo,
    api_bulk_memo,
    api_create_collection,
    api_create_memo,
    api_delete_collection,
    api_delete_memo,
    api_export_memos,
    api_list_collections,
    api_memo_detail,
    api_memo_share_detail,
    api_memo_share_refresh,
    api_memo_share_revoke,
    api_pin_memo,
    api_recent_memos,
    api_share_memo,
    api_shared_memo,
    api_suggest_memo,
    api_update_collection,
    api_update_memo,
    create_memo,
    memo_bp,
)


def _share_payload(share_state: dict[str, Any]) -> dict[str, Any]:
    share_token = str(share_state.get("share_token") or "")
    share_url = ""
    if share_token and bool(share_state.get("is_active")):
        share_url = frontend_url(f"/shared/memo/{share_token}")
    return {"status": "success", **share_state, "share_url": share_url}

__all__ = [
    "_build_csv_export",
    "_build_json_export",
    "_build_markdown_export",
    "_bulk_action",
    "_delete_collection",
    "_delete_memo",
    "_ensure_title",
    "_fetch_collections",
    "_fetch_memo_detail",
    "_fetch_memo_summaries",
    "_fetch_memos_for_export",
    "_insert_collection",
    "_insert_memo",
    "_schedule_embedding",
    "_set_memo_archive_state",
    "_set_memo_pin_state",
    "_share_payload",
    "_update_collection",
    "_update_memo",
    "api_archive_memo",
    "api_bulk_memo",
    "api_create_collection",
    "api_create_memo",
    "api_delete_collection",
    "api_delete_memo",
    "api_export_memos",
    "api_list_collections",
    "api_memo_detail",
    "api_memo_share_detail",
    "api_memo_share_refresh",
    "api_memo_share_revoke",
    "api_pin_memo",
    "api_recent_memos",
    "api_share_memo",
    "api_shared_memo",
    "api_suggest_memo",
    "api_update_collection",
    "api_update_memo",
    "create_or_get_shared_memo_token",
    "create_memo",
    "frontend_url",
    "embeddings_available",
    "generate_embedding",
    "get_db_connection",
    "get_memo_share_state",
    "get_shared_memo_payload",
    "memo_bp",
    "revoke_shared_memo_token",
    "suggest_title",
]
