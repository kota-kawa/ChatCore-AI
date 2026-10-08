"""Backend relay of web-search images shown inside a generated UI.

生成UIのサンドボックスは不透明オリジンで動き、Cookie を送らない。そのためこの経路は
セッションではなく、サーバーが選んだ画像URLにだけ付く署名で守る。署名が合わないURLは
取得せず、取得できなかった場合と同じ 404 を返す。

The generated-UI sandbox runs on an opaque origin and sends no cookie, so this route is guarded
by the signature the server puts only on image URLs it selected, not by the session. A URL
whose signature does not match is never fetched and answers the same 404 as a failed fetch.
"""

from __future__ import annotations

from fastapi.responses import Response

from services.async_utils import run_blocking
from services.error_messages import ERROR_CHAT_IMAGE_NOT_FOUND
from services.web import jsonify
from services.web_search_image_proxy import load_web_search_image, resolve_web_search_image_proxy_url

from . import chat_bp


@chat_bp.get("/api/chat/web-images/{signature}/{token}", name="chat.get_web_search_image")
async def get_web_search_image(signature: str, token: str):
    image_url = resolve_web_search_image_proxy_url(signature, token)
    if image_url is None:
        return jsonify({"error": ERROR_CHAT_IMAGE_NOT_FOUND}, status_code=404)
    image = await run_blocking(load_web_search_image, image_url)
    if image is None:
        return jsonify({"error": ERROR_CHAT_IMAGE_NOT_FOUND}, status_code=404)
    # 公開Webの画像なので共有キャッシュに載せてよい。元サイトの差し替えに追従できるよう1日で切る。
    # A public web image may sit in shared caches; one day keeps up with the origin replacing it.
    return Response(
        content=image.data,
        media_type=image.media_type,
        headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )
