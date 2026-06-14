from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from services.attached_files import encode_attached_files_for_storage

from .cache import get_redis_client

logger = logging.getLogger(__name__)


# 日本語: EphemeralChatStore に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to EphemeralChatStore.
class EphemeralChatStore:
    # 未ログインユーザーの一時チャットを Redis またはメモリで保持するストア
    # Store guest ephemeral chats in Redis when available, otherwise in-memory.
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, expiration_seconds: int) -> None:
        self.expiration_seconds = expiration_seconds
        self._memory = {}
        self._redis = None
        self._redis_initialized = False

    # 日本語: get redis の取得処理を担当します。
    # English: Handle fetching for get redis.
    def _get_redis(self):
        # Avoid network access during module import; CI/unit tests often import
        # chat routes without a Redis service available.
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not self._redis_initialized:
            self._redis = get_redis_client()
            self._redis_initialized = True
        return self._redis

    # 日本語: key に関する処理の入口です。
    # English: Entry point for logic related to key.
    def _key(self, sid: str, room_id: str) -> str:
        return f"ephemeral:{sid}:{room_id}"

    # 日本語: encode に関する処理の入口です。
    # English: Entry point for logic related to encode.
    def _encode(self, room: dict) -> str:
        return json.dumps(room, ensure_ascii=False)

    # 日本語: decode に関する処理の入口です。
    # English: Entry point for logic related to decode.
    def _decode(self, payload: str) -> dict:
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            logger.warning("Failed to decode ephemeral room payload; using empty fallback.", exc_info=True)
            return {}

    # 日本語: created at from room に関する処理の入口です。
    # English: Entry point for logic related to created at from room.
    def _created_at_from_room(self, room: dict) -> Optional[datetime]:
        created_at = room.get("created_at")
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not created_at:
            return None
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if isinstance(created_at, datetime):
            return created_at
        try:
            return datetime.fromisoformat(created_at)
        except (TypeError, ValueError):
            return None

    # 日本語: remaining ttl に関する処理の入口です。
    # English: Entry point for logic related to remaining ttl.
    def _remaining_ttl(self, room: dict) -> int:
        created_at = self._created_at_from_room(room)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if created_at is None:
            return self.expiration_seconds
        elapsed = (datetime.now() - created_at).total_seconds()
        remaining = int(self.expiration_seconds - elapsed)
        return max(0, remaining)

    # 日本語: is expired に関する処理の入口です。
    # English: Entry point for logic related to is expired.
    def _is_expired(self, room: dict) -> bool:
        created_at = self._created_at_from_room(room)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if created_at is None:
            return False
        return (datetime.now() - created_at).total_seconds() > self.expiration_seconds

    # 日本語: cleanup に関する処理の入口です。
    # English: Entry point for logic related to cleanup.
    def cleanup(self) -> None:
        # Redis利用時はTTL管理に任せ、メモリ利用時のみ期限切れルームを掃除する
        # Let Redis TTL handle expiry; prune expired rooms only for in-memory mode.
        redis_client = self._get_redis()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is not None:
            return
        sids_to_delete = []
        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
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

    # 日本語: create room の作成処理を担当します。
    # English: Handle creating for create room.
    def create_room(self, sid: str, room_id: str, title: str) -> None:
        # 新規ルームを作成し、作成時刻を保持して有効期限計算に使う
        # Create a room and keep creation time for TTL calculations.
        room = {
            "title": title,
            "messages": [],
            "created_at": datetime.now().isoformat(),
        }
        redis_client = self._get_redis()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is not None:
            key = self._key(sid, room_id)
            redis_client.set(key, self._encode(room), ex=self.expiration_seconds)
            return

        self._memory.setdefault(sid, {})[room_id] = room

    # 日本語: get room の取得処理を担当します。
    # English: Handle fetching for get room.
    def get_room(self, sid: str, room_id: str) -> Optional[dict]:
        # 取得時にも期限切れを判定し、期限超過ルームは削除して None を返す
        # Validate expiry on read and delete expired rooms before returning None.
        redis_client = self._get_redis()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is not None:
            key = self._key(sid, room_id)
            payload = redis_client.get(key)
            if not payload:
                return None
            room = self._decode(payload)
            if not room:
                redis_client.delete(key)
                return None
            if self._is_expired(room):
                redis_client.delete(key)
                return None
            return room

        return self._memory.get(sid, {}).get(room_id)

    # 日本語: room exists に関する処理の入口です。
    # English: Entry point for logic related to room exists.
    def room_exists(self, sid: str, room_id: str) -> bool:
        return self.get_room(sid, room_id) is not None

    # 日本語: save room の保存処理を担当します。
    # English: Handle saving for save room.
    def _save_room(self, sid: str, room_id: str, room: dict) -> bool:
        # Redis では残TTLを再計算して保存し、期限切れなら保存せず削除する
        # Recalculate remaining TTL for Redis; delete instead of saving when expired.
        redis_client = self._get_redis()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is not None:
            key = self._key(sid, room_id)
            ttl = self._remaining_ttl(room)
            if ttl <= 0:
                redis_client.delete(key)
                return False
            redis_client.set(key, self._encode(room), ex=ttl)
            return True

        self._memory.setdefault(sid, {})[room_id] = room
        return True

    # 日本語: delete room の削除処理を担当します。
    # English: Handle deleting for delete room.
    def delete_room(self, sid: str, room_id: str) -> bool:
        redis_client = self._get_redis()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is not None:
            return redis_client.delete(self._key(sid, room_id)) > 0

        rooms = self._memory.get(sid)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not rooms or room_id not in rooms:
            return False
        del rooms[room_id]
        if not rooms:
            del self._memory[sid]
        return True

    # 日本語: delete messages from trailing user count の削除処理を担当します。
    # English: Handle deleting for delete messages from trailing user count.
    def delete_messages_from_trailing_user_count(self, sid: str, room_id: str, trailing_user_count: int) -> bool:
        """Delete messages from the user message that has `trailing_user_count` user messages after it."""
        room = self.get_room(sid, room_id)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not room:
            return False
        messages = room.get("messages") or []
        user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if len(user_indices) <= trailing_user_count:
            return False
        target_msg_index = user_indices[len(user_indices) - 1 - trailing_user_count]
        room["messages"] = messages[:target_msg_index]
        return self._save_room(sid, room_id, room)

    # 日本語: delete last assistant message の削除処理を担当します。
    # English: Handle deleting for delete last assistant message.
    def delete_last_assistant_message(self, sid: str, room_id: str) -> bool:
        """Delete the last assistant message (and any messages after it) from an ephemeral room."""
        room = self.get_room(sid, room_id)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not room:
            return False
        messages = room.get("messages") or []
        last_idx = -1
        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
        for i, message in enumerate(messages):
            if message.get("role") == "assistant":
                last_idx = i
        if last_idx < 0:
            return False
        room["messages"] = messages[:last_idx]
        return self._save_room(sid, room_id, room)

    # 日本語: delete room if no assistant messages の削除処理を担当します。
    # English: Handle deleting for delete room if no assistant messages.
    def delete_room_if_no_assistant_messages(self, sid: str, room_id: str) -> bool:
        room = self.get_room(sid, room_id)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not room:
            return False

        messages = room.get("messages") or []
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if any(message.get("role") == "assistant" for message in messages):
            return False

        return self.delete_room(sid, room_id)

    # 日本語: rename room に関する処理の入口です。
    # English: Entry point for logic related to rename room.
    def rename_room(self, sid: str, room_id: str, new_title: str) -> bool:
        room = self.get_room(sid, room_id)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not room:
            return False
        room["title"] = new_title
        return self._save_room(sid, room_id, room)

    # 日本語: append message に関する処理の入口です。
    # English: Entry point for logic related to append message.
    def append_message(
        self,
        sid: str,
        room_id: str,
        role: str,
        content: str,
        message_parts: list[dict] | None = None,
        attached_file_contents: list | None = None,
    ) -> bool:
        # 指定ルームへメッセージを追記して永続化する
        # Append a message to the room and persist updated state.
        room = self.get_room(sid, room_id)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not room:
            return False
        messages = room.get("messages") or []
        entry = {"role": role, "content": content}
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if message_parts:
            entry["message_parts"] = message_parts
        if attached_file_contents:
            encoded_attached_files = encode_attached_files_for_storage(attached_file_contents)
            if encoded_attached_files:
                entry["attached_file_contents"] = json.loads(encoded_attached_files)
        messages.append(entry)
        room["messages"] = messages
        return self._save_room(sid, room_id, room)

    # 日本語: get messages の取得処理を担当します。
    # English: Handle fetching for get messages.
    def get_messages(self, sid: str, room_id: str) -> list:
        room = self.get_room(sid, room_id)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not room:
            return []
        return room.get("messages") or []

    # 日本語: list rooms の一覧取得処理を担当します。
    # English: Handle listing for list rooms.
    def list_rooms(self, sid: str) -> list[dict]:
        # sid 単位の一時ルーム一覧を返す
        # Return ephemeral room metadata for the given sid.
        rooms: list[dict] = []

        redis_client = self._get_redis()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is not None:
            key_prefix = self._key(sid, "")
            for key in redis_client.scan_iter(match=f"{key_prefix}*"):
                room_id = key[len(key_prefix):]
                if not room_id:
                    continue
                room = self.get_room(sid, room_id)
                if not room:
                    continue
                rooms.append(
                    {
                        "id": room_id,
                        "title": str(room.get("title") or "新規チャット"),
                        "created_at": room.get("created_at") or "",
                    }
                )
            return rooms

        self.cleanup()
        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
        for room_id, room in (self._memory.get(sid) or {}).items():
            rooms.append(
                {
                    "id": room_id,
                    "title": str(room.get("title") or "新規チャット"),
                    "created_at": room.get("created_at") or "",
                }
            )
        return rooms
