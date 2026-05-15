from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from services.datetime_serialization import serialize_datetime_iso
from services.web import frontend_url as default_frontend_url

from .constants import DEFAULT_EXCERPT_LENGTH
from .helpers import parse_memo_text


def _frontend_url(path: str) -> str:
    memo_module = sys.modules.get("blueprints.memo")
    if memo_module is not None:
        return getattr(memo_module, "frontend_url", default_frontend_url)(path)
    return default_frontend_url(path)


def is_expired(expires_at: Any) -> bool:
    if not isinstance(expires_at, datetime):
        return False
    return expires_at <= datetime.utcnow()


def serialize_share_meta(memo: dict[str, Any]) -> dict[str, Any]:
    share_token = memo.get("share_token") or ""
    expires_at = memo.get("expires_at")
    revoked_at = memo.get("revoked_at")
    is_active = bool(share_token) and revoked_at is None and not is_expired(expires_at)
    return {
        "share_token": share_token,
        "expires_at": serialize_datetime_iso(expires_at),
        "revoked_at": serialize_datetime_iso(revoked_at),
        "is_expired": is_expired(expires_at),
        "is_revoked": revoked_at is not None,
        "is_active": is_active,
        "share_url": _frontend_url(f"/shared/memo/{share_token}") if is_active else "",
    }


def serialize_memo_summary(memo: dict[str, Any]) -> dict[str, Any]:
    preview_source = parse_memo_text(memo.get("preview_response") or "")
    share_meta = serialize_share_meta(memo)
    return {
        "id": memo.get("id"),
        "title": memo.get("title") or "保存したメモ",
        "tags": memo.get("tags") or "",
        "created_at": serialize_datetime_iso(memo.get("created_at")),
        "updated_at": serialize_datetime_iso(memo.get("updated_at")),
        "archived_at": serialize_datetime_iso(memo.get("archived_at")),
        "pinned_at": serialize_datetime_iso(memo.get("pinned_at")),
        "is_archived": memo.get("archived_at") is not None,
        "is_pinned": memo.get("pinned_at") is not None,
        "excerpt": preview_source[:DEFAULT_EXCERPT_LENGTH],
        "collection_id": memo.get("collection_id"),
        "collection_name": memo.get("collection_name"),
        "collection_color": memo.get("collection_color"),
        **share_meta,
    }


def serialize_memo_detail(memo: dict[str, Any]) -> dict[str, Any]:
    share_meta = serialize_share_meta(memo)
    return {
        "id": memo.get("id"),
        "title": memo.get("title") or "保存したメモ",
        "tags": memo.get("tags") or "",
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
        **share_meta,
    }


def share_payload(share_state: dict[str, Any]) -> dict[str, Any]:
    share_token = str(share_state.get("share_token") or "")
    share_url = ""
    if share_token and bool(share_state.get("is_active")):
        share_url = _frontend_url(f"/shared/memo/{share_token}")
    return {"status": "success", **share_state, "share_url": share_url}
