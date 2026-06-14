from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from services.attached_files import encode_attached_files_for_storage

from .cache import get_redis_client

logger = logging.getLogger(__name__)


# 日本語: 未ログインユーザーの一時チャットデータを管理するクラス。Redisが利用可能な場合はRedisを使用し、利用不可の場合はオンメモリで保存します。
# English: Class managing guest ephemeral chat data. Uses Redis if available, otherwise falls back to in-memory storage.
class EphemeralChatStore:
    # 未ログインユーザーの一時チャットを Redis またはメモリで保持するストア
    # Store guest ephemeral chats in Redis when available, otherwise in-memory.
    # 日本語: 有効期限を設定し、メモリ用の辞書とRedis用の状態変数を初期化します。
    # English: Set the expiration duration and initialize the in-memory dictionary and Redis state variables.
    def __init__(self, expiration_seconds: int) -> None:
        self.expiration_seconds = expiration_seconds
        self._memory = {}
        self._redis = None
        self._redis_initialized = False

    # 日本語: 遅延初期化でRedisクライアントを取得します。
    # English: Retrieve the Redis client using lazy initialization.
    def _get_redis(self):
        # Avoid network access during module import; CI/unit tests often import
        # chat routes without a Redis service available.
        # 日本語: Redisクライアントがまだ初期化されていない場合、初期化を行います。
        # English: Initialize the Redis client if it has not been initialized yet.
        if not self._redis_initialized:
            self._redis = get_redis_client()
            self._redis_initialized = True
        return self._redis

    # 日本語: 一時チャットのRedisキーまたはメモリキーを生成します。
    # English: Generate the Redis or memory key for ephemeral chat.
    def _key(self, sid: str, room_id: str) -> str:
        return f"ephemeral:{sid}:{room_id}"

    # 日本語: チャットルームのデータをJSON文字列にエンコードします。
    # English: Encode chat room data into a JSON string.
    def _encode(self, room: dict) -> str:
        return json.dumps(room, ensure_ascii=False)

    # 日本語: JSON文字列からチャットルームのデータをデコードします。
    # English: Decode chat room data from a JSON string.
    def _decode(self, payload: str) -> dict:
        # 日本語: ペイロードのデコードを試みます。失敗した場合は空の辞書を返します。
        # English: Attempt to decode the payload. Return an empty dictionary on failure.
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            logger.warning("Failed to decode ephemeral room payload; using empty fallback.", exc_info=True)
            return {}

    # 日本語: ルーム情報から作成日時(datetime)をパースして取得します。
    # English: Parse and retrieve the creation datetime from the room data.
    def _created_at_from_room(self, room: dict) -> Optional[datetime]:
        created_at = room.get("created_at")
        # 日本語: 作成日時キーが存在しない場合は None を返します。
        # English: Return None if the creation time key does not exist.
        if not created_at:
            return None
        # 日本語: 既に datetime 型の場合はそのまま返し、文字列の場合はISO形式からパースします。
        # English: Return immediately if already a datetime instance, otherwise parse ISO format string.
        if isinstance(created_at, datetime):
            return created_at
        try:
            return datetime.fromisoformat(created_at)
        except (TypeError, ValueError):
            return None

    # 日本語: ルームの残り有効期限(TTL)を秒単位で計算します。
    # English: Calculate the remaining Time-To-Live (TTL) of the room in seconds.
    def _remaining_ttl(self, room: dict) -> int:
        created_at = self._created_at_from_room(room)
        # 日本語: 作成日時が取得できない場合はデフォルトの有効期限を返します。
        # English: Return the default expiration duration if the creation time is unavailable.
        if created_at is None:
            return self.expiration_seconds
        elapsed = (datetime.now() - created_at).total_seconds()
        remaining = int(self.expiration_seconds - elapsed)
        return max(0, remaining)

    # 日本語: ルームが有効期限切れしているかを判定します。
    # English: Check whether the room has expired.
    def _is_expired(self, room: dict) -> bool:
        created_at = self._created_at_from_room(room)
        # 日本語: 作成日時が取得できない場合は期限切れではないと判定します。
        # English: Treat as not expired if the creation time is unavailable.
        if created_at is None:
            return False
        return (datetime.now() - created_at).total_seconds() > self.expiration_seconds

    # 日本語: メモリ内の期限切れチャットルームを走査して削除します（Redis利用時はRedis側が自動制御するため不要）。
    # English: Scan and remove expired rooms from memory (not needed for Redis as it manages TTL automatically).
    def cleanup(self) -> None:
        # Redis利用時はTTL管理に任せ、メモリ利用時のみ期限切れルームを掃除する
        # Let Redis TTL handle expiry; prune expired rooms only for in-memory mode.
        redis_client = self._get_redis()
        # 日本語: Redisが設定されている場合は何もしません。
        # English: Do nothing if Redis is configured.
        if redis_client is not None:
            return
        sids_to_delete = []
        # 日本語: メモリ内のセッションごとのチャットルームをチェックして期限切れのものを削除します。
        # English: Check chat rooms for each session in memory and delete the expired ones.
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

    # 日本語: 新しいチャットルームを作成して保存します。
    # English: Create and store a new chat room.
    def create_room(self, sid: str, room_id: str, title: str) -> None:
        # 新規ルームを作成し、作成時刻を保持して有効期限計算に使う
        # Create a room and keep creation time for TTL calculations.
        room = {
            "title": title,
            "messages": [],
            "created_at": datetime.now().isoformat(),
        }
        redis_client = self._get_redis()
        # 日本語: Redisが利用可能な場合は、TTLを指定してRedisに保存します。
        # English: Save to Redis with the configured TTL if the Redis client is available.
        if redis_client is not None:
            key = self._key(sid, room_id)
            redis_client.set(key, self._encode(room), ex=self.expiration_seconds)
            return

        self._memory.setdefault(sid, {})[room_id] = room

    # 日本語: 指定されたチャットルームを取得します。期限切れの場合は自動的に削除します。
    # English: Retrieve the specified chat room. Deletes the room automatically if it has expired.
    def get_room(self, sid: str, room_id: str) -> Optional[dict]:
        # 取得時にも期限切れを判定し、期限超過ルームは削除して None を返す
        # Validate expiry on read and delete expired rooms before returning None.
        redis_client = self._get_redis()
        # 日本語: Redisが設定されている場合はRedisからデータを読み込みます。
        # English: Read room data from Redis if Redis is configured.
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

    # 日本語: チャットルームが存在するかどうかを確認します。
    # English: Check whether the chat room exists.
    def room_exists(self, sid: str, room_id: str) -> bool:
        return self.get_room(sid, room_id) is not None

    # 日本語: 更新されたチャットルームデータを永続化します。
    # English: Persist the updated chat room data.
    def _save_room(self, sid: str, room_id: str, room: dict) -> bool:
        # Redis では残TTLを再計算して保存し、期限切れなら保存せず削除する
        # Recalculate remaining TTL for Redis; delete instead of saving when expired.
        redis_client = self._get_redis()
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

    def delete_room(self, sid: str, room_id: str) -> bool:
        redis_client = self._get_redis()
        if redis_client is not None:
            return redis_client.delete(self._key(sid, room_id)) > 0

        rooms = self._memory.get(sid)
        if not rooms or room_id not in rooms:
            return False
        del rooms[room_id]
        if not rooms:
            del self._memory[sid]
        return True

    # 日本語: 指定されたユーザーメッセージ数よりも前のメッセージ履歴を削除します。
    # English: Delete message history prior to the specified trailing user message count.
    def delete_messages_from_trailing_user_count(self, sid: str, room_id: str, trailing_user_count: int) -> bool:
        """Delete messages from the user message that has `trailing_user_count` user messages after it."""
        room = self.get_room(sid, room_id)
        # 日本語: ルームが存在しない場合は False を返します。
        # English: Return False if the room does not exist.
        if not room:
            return False
        messages = room.get("messages") or []
        user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        # 日本語: ユーザーメッセージ数が指定数以下の場合は削除を行いません。
        # English: Do not delete if the number of user messages is less than or equal to the trailing count.
        if len(user_indices) <= trailing_user_count:
            return False
        target_msg_index = user_indices[len(user_indices) - 1 - trailing_user_count]
        room["messages"] = messages[:target_msg_index]
        return self._save_room(sid, room_id, room)

    # 日本語: 最後のAIアシスタントメッセージ（およびそれ以降のメッセージ）を削除します。
    # English: Remove the last assistant message (and any messages following it).
    def delete_last_assistant_message(self, sid: str, room_id: str) -> bool:
        """Delete the last assistant message (and any messages after it) from an ephemeral room."""
        room = self.get_room(sid, room_id)
        # 日本語: ルームが存在しない場合は False を返します。
        # English: Return False if the room does not exist.
        if not room:
            return False
        messages = room.get("messages") or []
        last_idx = -1
        # 日本語: メッセージ履歴を末尾から走査して、最後のアシスタントメッセージのインデックスを特定します。
        # English: Scan message history from the end to identify the last assistant message index.
        for i, message in enumerate(messages):
            if message.get("role") == "assistant":
                last_idx = i
        if last_idx < 0:
            return False
        room["messages"] = messages[:last_idx]
        return self._save_room(sid, room_id, room)

    # 日本語: ルーム内にAIアシスタントからの返答がない場合、ルームを削除します。
    # English: Delete the room if it contains no response messages from the assistant.
    def delete_room_if_no_assistant_messages(self, sid: str, room_id: str) -> bool:
        room = self.get_room(sid, room_id)
        # 日本語: ルームが存在しない場合は False を返します。
        # English: Return False if the room does not exist.
        if not room:
            return False

        messages = room.get("messages") or []
        # 日本語: アシスタントからのメッセージが1つでもある場合は削除せずに False を返します。
        # English: Return False without deleting if there is at least one assistant message.
        if any(message.get("role") == "assistant" for message in messages):
            return False

        return self.delete_room(sid, room_id)

    # 日本語: ルームのタイトルを変更します。
    # English: Rename the chat room title.
    def rename_room(self, sid: str, room_id: str, new_title: str) -> bool:
        room = self.get_room(sid, room_id)
        # 日本語: ルームが存在しない場合は False を返します。
        # English: Return False if the room does not exist.
        if not room:
            return False
        room["title"] = new_title
        return self._save_room(sid, room_id, room)

    # 日本語: ルームに新しいメッセージ（および添付ファイル情報）を追加します。
    # English: Append a new message (along with optional attachment metadata) to the room.
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
        # 日本語: ルームが存在しない場合は False を返します。
        # English: Return False if the room does not exist.
        if not room:
            return False
        messages = room.get("messages") or []
        entry = {"role": role, "content": content}
        # 日本語: メッセージパーツや添付ファイルがある場合は追加のメタデータに含めます。
        # English: Include additional metadata if message parts or file attachments exist.
        if message_parts:
            entry["message_parts"] = message_parts
        if attached_file_contents:
            encoded_attached_files = encode_attached_files_for_storage(attached_file_contents)
            if encoded_attached_files:
                entry["attached_file_contents"] = json.loads(encoded_attached_files)
        messages.append(entry)
        room["messages"] = messages
        return self._save_room(sid, room_id, room)

    # 日本語: 指定されたルームのメッセージ履歴リストを取得します。
    # English: Retrieve the list of messages in the specified room.
    def get_messages(self, sid: str, room_id: str) -> list:
        room = self.get_room(sid, room_id)
        # 日本語: ルームが存在しない場合は空リストを返します。
        # English: Return an empty list if the room does not exist.
        if not room:
            return []
        return room.get("messages") or []

    # 日本語: 特定のセッションに紐づく有効なチャットルームの一覧を取得します。
    # English: List active chat rooms associated with the given session ID.
    def list_rooms(self, sid: str) -> list[dict]:
        # sid 単位の一時ルーム一覧を返す
        # Return ephemeral room metadata for the given sid.
        rooms: list[dict] = []

        redis_client = self._get_redis()
        # 日本語: Redisが設定されている場合はスキャンしてルームメタデータを取得します。
        # English: Scan Redis keys and compile room metadata if Redis is configured.
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
        # 日本語: メモリ内のルーム情報からメタデータリストを構築して返します。
        # English: Compile and return the list of room metadata from the in-memory store.
        for room_id, room in (self._memory.get(sid) or {}).items():
            rooms.append(
                {
                    "id": room_id,
                    "title": str(room.get("title") or "新規チャット"),
                    "created_at": room.get("created_at") or "",
                }
            )
        return rooms
