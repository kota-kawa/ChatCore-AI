from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from .cache import get_redis_client

logger = logging.getLogger(__name__)


class EphemeralChatStore:
    # 未ログインユーザーの一時チャットを Redis またはメモリで保持するストア
    # Store guest ephemeral chats in Redis when available, otherwise in-memory.
    def __init__(self, expiration_seconds: int) -> None:
        self.expiration_seconds = expiration_seconds
        self._memory = {}
        self._redis = get_redis_client()

    def _key(self, sid: str, room_id: str) -> str:
        return f"ephemeral:{sid}:{room_id}"

    def _encode(self, room: dict) -> str:
        return json.dumps(room, ensure_ascii=False)

    def _decode(self, payload: str) -> dict:
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            logger.warning("Failed to decode ephemeral room payload; using empty fallback.", exc_info=True)
            return {}

    def _created_at_from_room(self, room: dict) -> Optional[datetime]:
        created_at = room.get("created_at")
        if not created_at:
            return None
        if isinstance(created_at, datetime):
            return created_at
        try:
            return datetime.fromisoformat(created_at)
        except (TypeError, ValueError):
            return None

    def _remaining_ttl(self, room: dict) -> int:
        created_at = self._created_at_from_room(room)
        if created_at is None:
            return self.expiration_seconds
        elapsed = (datetime.now() - created_at).total_seconds()
        remaining = int(self.expiration_seconds - elapsed)
        return max(0, remaining)

    def _is_expired(self, room: dict) -> bool:
        created_at = self._created_at_from_room(room)
        if created_at is None:
            return False
        return (datetime.now() - created_at).total_seconds() > self.expiration_seconds

    def cleanup(self) -> None:
        # Redis利用時はTTL管理に任せ、メモリ利用時のみ期限切れルームを掃除する
        # Let Redis TTL handle expiry; prune expired rooms only for in-memory mode.
        if self._redis is not None:
            return
        sids_to_delete = []
        for sid, rooms in self._memory.items():
            room_ids_to_delete = []
            for room_id, room_data in rooms.items():
                if self._is_expired(room_data):
                    room_ids_to_delete.append(room_id)
            for room_id in room_ids_to_delete:
                del rooms[room_id]
            if not rooms:
                sids_to_delete.append(sid)
        for sid in sids_to_delete:
            del self._memory[sid]

    def create_room(self, sid: str, room_id: str, title: str) -> None:
        # 新規ルームを作成し、作成時刻を保持して有効期限計算に使う
        # Create a room and keep creation time for TTL calculations.
        room = {
            "title": title,
            "messages": [],
            "created_at": datetime.now().isoformat(),
        }
        if self._redis is not None:
            key = self._key(sid, room_id)
            self._redis.set(key, self._encode(room), ex=self.expiration_seconds)
            return

        self._memory.setdefault(sid, {})[room_id] = room

    def get_room(self, sid: str, room_id: str) -> Optional[dict]:
        # 取得時にも期限切れを判定し、期限超過ルームは削除して None を返す
        # Validate expiry on read and delete expired rooms before returning None.
        if self._redis is not None:
            key = self._key(sid, room_id)
            payload = self._redis.get(key)
            if not payload:
                return None
            room = self._decode(payload)
            if not room:
                self._redis.delete(key)
                return None
            if self._is_expired(room):
                self._redis.delete(key)
                return None
            return room

        return self._memory.get(sid, {}).get(room_id)

    def room_exists(self, sid: str, room_id: str) -> bool:
        return self.get_room(sid, room_id) is not None

    def _save_room(self, sid: str, room_id: str, room: dict) -> bool:
        # Redis では残TTLを再計算して保存し、期限切れなら保存せず削除する
        # Recalculate remaining TTL for Redis; delete instead of saving when expired.
        if self._redis is not None:
            key = self._key(sid, room_id)
            ttl = self._remaining_ttl(room)
            if ttl <= 0:
                self._redis.delete(key)
                return False
            self._redis.set(key, self._encode(room), ex=ttl)
            return True

        self._memory.setdefault(sid, {})[room_id] = room
        return True

    def delete_room(self, sid: str, room_id: str) -> bool:
        if self._redis is not None:
            return self._redis.delete(self._key(sid, room_id)) > 0

        rooms = self._memory.get(sid)
        if not rooms or room_id not in rooms:
            return False
        del rooms[room_id]
        if not rooms:
            del self._memory[sid]
        return True

    def rename_room(self, sid: str, room_id: str, new_title: str) -> bool:
        room = self.get_room(sid, room_id)
        if not room:
            return False
        room["title"] = new_title
        return self._save_room(sid, room_id, room)

    def append_message(self, sid: str, room_id: str, role: str, content: str) -> bool:
        # 指定ルームへメッセージを追記して永続化する
        # Append a message to the room and persist updated state.
        room = self.get_room(sid, room_id)
        if not room:
            return False
        messages = room.get("messages") or []
        messages.append({"role": role, "content": content})
        room["messages"] = messages
        return self._save_room(sid, room_id, room)

    def get_messages(self, sid: str, room_id: str) -> list:
        room = self.get_room(sid, room_id)
        if not room:
            return []
        return room.get("messages") or []
