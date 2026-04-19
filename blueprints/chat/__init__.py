from fastapi import APIRouter, Depends
import uuid

from services.csrf import require_csrf
from services.ephemeral_store import EphemeralChatStore

chat_bp = APIRouter(dependencies=[Depends(require_csrf)])

# エフェメラルチャットの有効期限（秒）
# Expiration time for guest ephemeral chats (seconds).
EXPIRATION_TIME = 3600  # 1時間
GUEST_ROOM_IDS_SESSION_KEY = "guest_room_ids"

# 未ログインユーザー用のエフェメラルチャットを保持するストア
# Store for guest (non-authenticated) ephemeral chat rooms.
ephemeral_store = EphemeralChatStore(EXPIRATION_TIME)


# セッションIDを取得/生成するヘルパー関数
# Helper to get or create session ID for guest chat isolation.
def get_session_id(session: dict) -> str:
    if "sid" not in session:
        session["sid"] = str(uuid.uuid4())
    return session["sid"]


def get_guest_room_ids(session: dict) -> list[str]:
    raw_room_ids = session.get(GUEST_ROOM_IDS_SESSION_KEY)
    if not isinstance(raw_room_ids, list):
        return []
    return [room_id for room_id in raw_room_ids if isinstance(room_id, str) and room_id]


def register_guest_room(session: dict, room_id: str) -> None:
    room_ids = get_guest_room_ids(session)
    if room_id in room_ids:
        return
    session[GUEST_ROOM_IDS_SESSION_KEY] = [*room_ids, room_id]


def unregister_guest_room(session: dict, room_id: str) -> None:
    room_ids = [existing_room_id for existing_room_id in get_guest_room_ids(session) if existing_room_id != room_id]
    if room_ids:
        session[GUEST_ROOM_IDS_SESSION_KEY] = room_ids
        return
    session.pop(GUEST_ROOM_IDS_SESSION_KEY, None)


def guest_room_belongs_to_session(session: dict, room_id: str) -> bool:
    return room_id in get_guest_room_ids(session)


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
    "get_guest_room_ids",
    "register_guest_room",
    "unregister_guest_room",
    "guest_room_belongs_to_session",
    "ephemeral_store",
    "EXPIRATION_TIME",
]
