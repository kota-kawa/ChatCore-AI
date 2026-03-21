from fastapi import APIRouter, Depends
import uuid

from services.csrf import require_csrf
from services.ephemeral_store import EphemeralChatStore

chat_bp = APIRouter(dependencies=[Depends(require_csrf)])

# エフェメラルチャットの有効期限（秒）
# Expiration time for guest ephemeral chats (seconds).
EXPIRATION_TIME = 3600  # 1時間

# 未ログインユーザー用のエフェメラルチャットを保持するストア
# Store for guest (non-authenticated) ephemeral chat rooms.
ephemeral_store = EphemeralChatStore(EXPIRATION_TIME)


# セッションIDを取得/生成するヘルパー関数
# Helper to get or create session ID for guest chat isolation.
def get_session_id(session: dict) -> str:
    if "sid" not in session:
        session["sid"] = str(uuid.uuid4())
    return session["sid"]


# エフェメラルチャットの期限切れデータを掃除する
# Clean up expired data from the ephemeral chat store.
def cleanup_ephemeral_chats():
    ephemeral_store.cleanup()


# ルートハンドラを import して APIRouter へ登録する
# Import route modules so handlers are registered on APIRouter.
from . import views, profile, rooms, messages, tasks  # noqa: F401, E402

__all__ = [
    "chat_bp",
    "cleanup_ephemeral_chats",
    "get_session_id",
    "ephemeral_store",
    "EXPIRATION_TIME",
]
