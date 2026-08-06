"""共有チャットを閲覧者自身のチャットとして複製する処理。

Forking a shared chat into the viewer's own chat room.

共有リンクは読み取り専用のままにし、「続きを話す」操作では会話を複製してから
続きを書き込む。こうすることで、リンクを知っている第三者が共有元の履歴
（所有者の chat_history ツリー）を書き換えられない状態を保てる。

The shared link itself stays read-only: continuing a shared conversation copies it first
and writes only into the copy, so nobody holding the link can modify the owner's history.
"""

from __future__ import annotations

from typing import Any, Protocol

from .chat_service import (
    copy_messages_into_chat_room,
    create_chat_room_in_db,
    get_shared_chat_room_payload,
)

# 1回の複製で引き継ぐメッセージ数の上限。極端に長い共有チャットの複製で
# DB書き込みが膨らむのを防ぐ（超過分は古い側から捨てず、先頭から上限まで引き継ぐ）。
# Cap on how many messages a single fork copies, so an extremely long shared chat cannot
# blow up the number of DB writes. The first N messages of the conversation are kept.
MAX_FORKED_MESSAGES = 500

DEFAULT_FORKED_ROOM_TITLE = "共有チャット"


# エフェメラルストアのうち、複製で使う操作だけを表す最小のインターフェース。
# Minimal interface of the ephemeral store used by the fork (keeps this module testable).
class EphemeralRoomStore(Protocol):
    def create_room(self, sid: str, room_id: str, title: str) -> None: ...

    def append_message(
        self,
        sid: str,
        room_id: str,
        role: str,
        content: str,
        message_parts: list[dict] | None = None,
        attached_file_contents: list | None = None,
        web_search_context: list[dict] | None = None,
    ) -> bool: ...


# 共有トークンから複製元のタイトルとメッセージ列を取り出す。
# トークンが無効な場合は get_shared_chat_room_payload が ResourceNotFoundError を投げる。
# Resolve the source title and messages for a share token. An invalid token makes
# get_shared_chat_room_payload raise ResourceNotFoundError.
def load_shared_chat_for_fork(token: str) -> tuple[str, list[dict[str, Any]]]:
    payload = get_shared_chat_room_payload(token)
    room = payload.get("room") if isinstance(payload, dict) else None
    raw_title = (room or {}).get("title") if isinstance(room, dict) else None
    title = str(raw_title).strip() if raw_title else ""

    raw_messages = payload.get("messages") if isinstance(payload, dict) else None
    messages = [message for message in (raw_messages or []) if isinstance(message, dict)]

    return title or DEFAULT_FORKED_ROOM_TITLE, messages[:MAX_FORKED_MESSAGES]


# ログインユーザー向け：DBに永続化される通常ルームとして複製する。
# Authenticated viewers: fork into a persisted normal room owned by them.
def fork_shared_chat_into_db_room(token: str, room_id: str, user_id: int) -> dict[str, Any]:
    title, messages = load_shared_chat_for_fork(token)
    create_chat_room_in_db(room_id, user_id, title, "normal")
    copied = copy_messages_into_chat_room(room_id, messages)
    return {"id": room_id, "title": title, "mode": "normal", "message_count": copied}


# 非ログインユーザー向け：エフェメラルストア上の一時ルームとして複製する。
# Guest viewers: fork into a temporary room held in the ephemeral store.
def fork_shared_chat_into_ephemeral_room(
    token: str,
    sid: str,
    room_id: str,
    store: EphemeralRoomStore,
) -> dict[str, Any]:
    title, messages = load_shared_chat_for_fork(token)
    store.create_room(sid, room_id, title)

    copied = 0
    for message in messages:
        role = "user" if message.get("sender") == "user" else "assistant"
        message_parts = message.get("message_parts")
        appended = store.append_message(
            sid,
            room_id,
            role,
            str(message.get("message") or ""),
            message_parts=message_parts if isinstance(message_parts, list) else None,
        )
        if not appended:
            break
        copied += 1

    return {"id": room_id, "title": title, "mode": "temporary", "message_count": copied}
