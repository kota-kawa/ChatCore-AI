"""Backend delivery of stored avatar images.

アバターは app コンテナのボリューム上にあるため、frontend コンテナからは配信
できない。nginx の backend location 正規表現に一致する ``/api/...`` 配下で
配信し、検証・Content-Type 決定・パストラバーサル対策は
``blueprints/prompt_share/prompt_share_api.py`` の添付配信と同じ形に揃える。

Avatars live on an app-container volume, so the frontend container cannot serve
them. This route sits under ``/api/...`` so the nginx backend location matches.
"""

from __future__ import annotations

import os

from fastapi.responses import FileResponse

from services.async_utils import run_blocking
from services.avatar_storage import (
    avatar_content_type,
    resolve_avatar_path,
    resolve_legacy_avatar_path,
)
from services.error_messages import ERROR_AVATAR_NOT_FOUND
from services.web import jsonify

from . import chat_bp


# アバター画像は公開プロフィールや公開プロンプトの著者表示にも使うため、
# 認証は要求せず、ファイル名検証だけで配信対象を限定する。
# Avatars also appear on public author cards, so the route stays unauthenticated
# and relies on strict filename validation to bound what can be served.
@chat_bp.get("/api/user/avatars/{filename}", name="chat.get_avatar_media")
async def get_avatar_media(filename: str):
    try:
        filepath = resolve_avatar_path(filename)
        media_type = avatar_content_type(filename)
    except ValueError:
        return jsonify({"error": ERROR_AVATAR_NOT_FOUND}, status_code=404)
    # イベントループを止めないため、ファイル存在確認はワーカースレッドで行う。
    # Run the blocking stat call on the worker thread so the event loop is not blocked.
    if not await run_blocking(os.path.isfile, filepath):
        # 旧配置（frontend/public/static/uploads）に残るファイルも読めるようにする。
        # Keep reading files left behind in the former frontend/public location.
        try:
            filepath = resolve_legacy_avatar_path(filename)
        except ValueError:
            return jsonify({"error": ERROR_AVATAR_NOT_FOUND}, status_code=404)
        if not await run_blocking(os.path.isfile, filepath):
            return jsonify({"error": ERROR_AVATAR_NOT_FOUND}, status_code=404)
    return FileResponse(
        filepath,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
    )
