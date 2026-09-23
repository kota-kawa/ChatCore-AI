"""Backend delivery of images attached to chat messages.

チャット画像は本人の会話でだけ使う私的なデータなので、公開のアバター配信とは違い、
画像IDに埋め込んだ持ち主と閲覧者のセッションが一致するときだけ返す。一致しない場合も
存在しない場合と同じ 404 にして、他人の画像IDの有無を推測させない。

Chat images are private, so unlike the public avatar route they are returned only when the
owner embedded in the image id matches the viewer's session. A mismatch answers 404 exactly
like a missing file, so nobody can probe whether another user's image id exists.
"""

from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import FileResponse

from services.async_utils import run_blocking
from services.chat_image_storage import (
    chat_image_belongs_to,
    chat_image_owner_key,
    resolve_chat_image_path,
)
from services.chat_images import CHAT_IMAGE_MEDIA_TYPE
from services.error_messages import ERROR_CHAT_IMAGE_NOT_FOUND
from services.web import jsonify

from . import chat_bp


async def _chat_image_response(request: Request, image_id: str, *, thumbnail: bool):
    session = request.session
    owner_key = chat_image_owner_key(user_id=session.get("user_id"), sid=session.get("sid"))
    if not chat_image_belongs_to(image_id, owner_key):
        return jsonify({"error": ERROR_CHAT_IMAGE_NOT_FOUND}, status_code=404)
    filepath = resolve_chat_image_path(image_id, thumbnail=thumbnail)
    # イベントループを止めないため、ファイル存在確認はワーカースレッドで行う。
    # Run the blocking stat call on the worker thread so the event loop is not blocked.
    if not await run_blocking(os.path.isfile, filepath):
        return jsonify({"error": ERROR_CHAT_IMAGE_NOT_FOUND}, status_code=404)
    # 画像IDごとに中身は変わらないので長く持たせるが、共有キャッシュには載せない。
    # Content never changes for an id, so cache it long, but never in a shared cache.
    return FileResponse(
        filepath,
        media_type=CHAT_IMAGE_MEDIA_TYPE,
        headers={"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
    )


@chat_bp.get("/api/chat/images/{image_id}", name="chat.get_chat_image")
async def get_chat_image(request: Request, image_id: str):
    return await _chat_image_response(request, image_id, thumbnail=False)


@chat_bp.get("/api/chat/images/{image_id}/thumbnail", name="chat.get_chat_image_thumbnail")
async def get_chat_image_thumbnail(request: Request, image_id: str):
    return await _chat_image_response(request, image_id, thumbnail=True)
