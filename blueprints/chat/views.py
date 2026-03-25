from fastapi import Request

from services.web import redirect_to_frontend

from . import chat_bp, cleanup_ephemeral_chats


@chat_bp.get("/", name="chat.index")
async def index(request: Request):
    # 画面表示前に不要な一時チャットを掃除し、フロント側ルートへ転送する
    # Clean stale ephemeral chats before rendering, then redirect to frontend route.
    cleanup_ephemeral_chats()
    return redirect_to_frontend(request)


@chat_bp.get("/settings", name="chat.settings")
async def settings(request: Request):
    # 設定画面も FastAPI 側では描画せず、フロントエンドへルーティングする
    # Keep settings rendering on frontend and only route from FastAPI.
    return redirect_to_frontend(request)
