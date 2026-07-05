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
    # セッションIDが無い場合、UUIDで新規生成してセッションに設定
    # If session ID does not exist, generate a new UUID and store it in session.
    if "sid" not in session:
        session["sid"] = str(uuid.uuid4())
    return session["sid"]


# セッションに登録されたゲスト用のチャットルームID一覧を取得する関数
# Retrieve the list of guest chat room IDs stored in the session.
def get_guest_room_ids(session: dict) -> list[str]:
    raw_room_ids = session.get(GUEST_ROOM_IDS_SESSION_KEY)
    if not isinstance(raw_room_ids, list):
        return []
    # 有効な文字列型のルームIDのみフィルタリングして返却
    # Filter and return only non-empty string room IDs.
    return [room_id for room_id in raw_room_ids if isinstance(room_id, str) and room_id]


# ゲスト用ルームIDをセッションに登録する関数
# Register a guest room ID in the session.
def register_guest_room(session: dict, room_id: str) -> None:
    room_ids = get_guest_room_ids(session)
    if room_id in room_ids:
        return
    # ルームIDリストの末尾に追加
    # Append the room ID to the list.
    session[GUEST_ROOM_IDS_SESSION_KEY] = [*room_ids, room_id]


# ゲスト用ルームIDをセッションから登録解除する関数
# Unregister/remove a guest room ID from the session.
def unregister_guest_room(session: dict, room_id: str) -> None:
    # 指定IDを除いた新規リストを作成
    # Construct a new list excluding the targeted room ID.
    room_ids = [existing_room_id for existing_room_id in get_guest_room_ids(session) if existing_room_id != room_id]
    if room_ids:
        session[GUEST_ROOM_IDS_SESSION_KEY] = room_ids
        return
    # 空になった場合はキーごと削除
    # If the list is empty, clear the session key.
    session.pop(GUEST_ROOM_IDS_SESSION_KEY, None)


# ゲスト/仮ユーザーのデータストアキーを取得する関数
# Generate a storage lookup key for a temporary/guest user.
def get_temporary_user_store_key(user_id: int) -> str:
    return f"temporary-user:{user_id}"


# エフェメラルチャットの期限切れデータを掃除する関数
# Clean up expired data from the ephemeral chat store.
def cleanup_ephemeral_chats():
    ephemeral_store.cleanup()


# ルートハンドラを import して APIRouter へ登録する
# Import route modules so handlers are registered on APIRouter.
from . import views, profile, rooms, messages, tasks, projects  # noqa: F401, E402

__all__ = [
    "chat_bp",
    "cleanup_ephemeral_chats",
    "get_session_id",
    "get_guest_room_ids",
    "register_guest_room",
    "unregister_guest_room",
    "get_temporary_user_store_key",
    "ephemeral_store",
    "EXPIRATION_TIME",
]
