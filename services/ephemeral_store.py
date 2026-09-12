from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime

from services.attached_files import encode_attached_files_for_storage

from .cache import get_redis_client

try:  # pragma: no cover - redis is an optional dependency in test environments
    from redis.exceptions import WatchError
except ModuleNotFoundError:  # pragma: no cover - optional dependency

    # redis 未導入の環境でも import できるよう、決して送出されない代替例外を用意する。
    # Provide a stand-in exception that is never raised so the module imports without redis.
    class WatchError(Exception):  # type: ignore[no-redef]
        """Placeholder used when the redis package is not installed."""


logger = logging.getLogger(__name__)

# 楽観ロックが衝突したときに read-modify-write をやり直す最大回数。
# Maximum number of read-modify-write attempts after optimistic-lock conflicts.
MAX_ROOM_MUTATION_ATTEMPTS = 8

# ルームキーを割り当てるロックの本数。ルームは無数に作られるためキーごとに
# ロックを溜め込まず、固定本数へハッシュで振り分ける。
# Number of locks room keys are hashed onto. Rooms are created endlessly, so a
# bounded stripe set is used instead of accumulating one lock per key.
ROOM_LOCK_STRIPE_COUNT = 64

# ルームへの変更を表すコールバック。保存が必要なら True を返す。
# Callback applying a change to a room; returns True when the result must be saved.
RoomMutation = Callable[[dict], bool]


# キー単位の排他を固定本数のロックで提供するヘルパー。
# Helper providing per-key mutual exclusion with a bounded number of locks.
class _StripedLocks:
    def __init__(self, stripe_count: int) -> None:
        self._locks = [threading.RLock() for _ in range(stripe_count)]

    # キーに対応するロックを返します（同じキーは常に同じロック）。
    # Return the lock assigned to a key (the same key always maps to the same lock).
    def get(self, key: str):
        return self._locks[hash(key) % len(self._locks)]


# 未ログインユーザーの一時チャットデータを管理するクラス。Redisが利用可能な場合はRedisを使用し、利用不可の場合はオンメモリで保存します。
# Class managing guest ephemeral chat data. Uses Redis if available, otherwise falls back to in-memory storage.
class EphemeralChatStore:
    # 未ログインユーザーの一時チャットを Redis またはメモリで保持するストア。
    # Store guest ephemeral chats in Redis when available, otherwise in-memory.
    # 有効期限を設定し、メモリ用の辞書とRedis用の状態変数を初期化します。
    # Set the expiration duration and initialize the in-memory dictionary and Redis state variables.
    def __init__(self, expiration_seconds: int) -> None:
        self.expiration_seconds = expiration_seconds
        self._memory = {}
        self._redis = None
        # メモリ実装は複数の生成ワーカースレッドから同時に触られるため、辞書操作を直列化する。
        # The in-memory fallback is touched by several generation worker threads, so serialize dict access.
        self._memory_lock = threading.RLock()
        # read-modify-write をルーム単位で直列化するためのロック。
        # Locks serializing read-modify-write sequences per room.
        self._room_locks = _StripedLocks(ROOM_LOCK_STRIPE_COUNT)

    # 遅延初期化でRedisクライアントを取得します。
    # Retrieve the Redis client using lazy initialization.
    def _get_redis(self):
        # Avoid network access during module import; CI/unit tests often import
        # chat routes without a Redis service available.
        # 取得できたクライアントだけをキャッシュする。None をキャッシュすると Redis 断や
        # クールダウン中に一度空振りしただけで、そのワーカーは二度と Redis を使わなくなり、
        # ゲストの履歴がプロセスローカルのメモリに閉じ込められてしまう。
        # Cache only a real client. Caching None would latch this worker into the
        # in-memory fallback for its whole lifetime after a single miss during a
        # Redis outage or the retry cooldown, losing guest history across workers.
        # 再取得のコストは `get_redis_client()` 側のクールダウンで抑えられている。
        # The cost of retrying is bounded by the cooldown inside `get_redis_client()`.
        if self._redis is None:
            self._redis = get_redis_client()
        return self._redis

    # 一時チャットのRedisキーまたはメモリキーを生成します。
    # Generate the Redis or memory key for ephemeral chat.
    def _key(self, sid: str, room_id: str) -> str:
        return f"ephemeral:{sid}:{room_id}"

    # チャットルームのデータをJSON文字列にエンコードします。
    # Encode chat room data into a JSON string.
    def _encode(self, room: dict) -> str:
        return json.dumps(room, ensure_ascii=False)

    # JSON文字列からチャットルームのデータをデコードします。
    # Decode chat room data from a JSON string.
    def _decode(self, payload: str) -> dict:
        # ペイロードのデコードを試みます。失敗した場合は空の辞書を返します。
        # Attempt to decode the payload. Return an empty dictionary on failure.
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            logger.warning("Failed to decode ephemeral room payload; using empty fallback.", exc_info=True)
            return {}

    # ISO文字列またはdatetimeを datetime へ正規化します。
    # Normalize an ISO string or datetime value into a datetime.
    def _parse_timestamp(self, value: object) -> datetime | None:
        # 値が存在しない場合は None を返します。
        # Return None when the value is missing.
        if not value:
            return None
        # 既に datetime 型の場合はそのまま返し、文字列の場合はISO形式からパースします。
        # Return immediately if already a datetime instance, otherwise parse ISO format string.
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    # 有効期限の起点となる「最終利用時刻」を取得します。
    # Retrieve the last-activity timestamp used as the expiry baseline.
    def _expiry_baseline(self, room: dict) -> datetime | None:
        # 有効期限は作成時刻ではなく最終利用時刻から数える。会話中に突然ルームが
        # 消えて「該当ルームが見つかりません」になるのを防ぐため。
        # Expiry is counted from the last activity instead of the creation time so
        # a room in active use never vanishes mid-conversation.
        return self._parse_timestamp(room.get("last_active_at")) or self._parse_timestamp(
            room.get("created_at")
        )

    # ルームの残り有効期限(TTL)を秒単位で計算します。
    # Calculate the remaining Time-To-Live (TTL) of the room in seconds.
    def _remaining_ttl(self, room: dict) -> int:
        baseline = self._expiry_baseline(room)
        # 起点が取得できない場合はデフォルトの有効期限を返します。
        # Return the default expiration duration if the baseline is unavailable.
        if baseline is None:
            return self.expiration_seconds
        elapsed = (datetime.now() - baseline).total_seconds()
        remaining = int(self.expiration_seconds - elapsed)
        return max(0, remaining)

    # ルームが有効期限切れしているかを判定します。
    # Check whether the room has expired.
    def _is_expired(self, room: dict) -> bool:
        baseline = self._expiry_baseline(room)
        # 起点が取得できない場合は期限切れではないと判定します。
        # Treat as not expired if the baseline is unavailable.
        if baseline is None:
            return False
        return (datetime.now() - baseline).total_seconds() > self.expiration_seconds

    # メモリ内の期限切れチャットルームを走査して削除します（Redis利用時はRedis側が自動制御するため不要）。
    # Scan and remove expired rooms from memory (not needed for Redis as it manages TTL automatically).
    def cleanup(self) -> None:
        # Redis利用時はTTL管理に任せ、メモリ利用時のみ期限切れルームを掃除する
        # Let Redis TTL handle expiry; prune expired rooms only for in-memory mode.
        redis_client = self._get_redis()
        # Redisが設定されている場合は何もしません。
        # Do nothing if Redis is configured.
        if redis_client is not None:
            return
        # 走査中に別スレッドがルームを足すと反復が壊れるため、掃除全体をロックで囲う。
        # Another thread adding a room mid-scan would break the iteration, so hold the lock throughout.
        with self._memory_lock:
            sids_to_delete = []
            # メモリ内のセッションごとのチャットルームをチェックして期限切れのものを削除します。
            # Check chat rooms for each session in memory and delete the expired ones.
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

    # 新しいチャットルームを作成して保存します。
    # Create and store a new chat room.
    def create_room(self, sid: str, room_id: str, title: str) -> None:
        # 新規ルームを作成し、作成時刻を保持して有効期限計算に使う
        # Create a room and keep creation time for TTL calculations.
        created_at = datetime.now().isoformat()
        room = {
            "title": title,
            "messages": [],
            "created_at": created_at,
            "last_active_at": created_at,
        }
        redis_client = self._get_redis()
        # Redisが利用可能な場合は、TTLを指定してRedisに保存します。
        # Save to Redis with the configured TTL if the Redis client is available.
        if redis_client is not None:
            key = self._key(sid, room_id)
            redis_client.set(key, self._encode(room), ex=self.expiration_seconds)
            return

        with self._memory_lock:
            self._memory.setdefault(sid, {})[room_id] = room

    # 指定されたチャットルームを取得します。期限切れの場合は自動的に削除します。
    # Retrieve the specified chat room. Deletes the room automatically if it has expired.
    def get_room(self, sid: str, room_id: str) -> dict | None:
        # 取得時にも期限切れを判定し、期限超過ルームは削除して None を返す
        # Validate expiry on read and delete expired rooms before returning None.
        redis_client = self._get_redis()
        # Redisが設定されている場合はRedisからデータを読み込みます。
        # Read room data from Redis if Redis is configured.
        if redis_client is not None:
            return self._read_room_from_redis(redis_client, self._key(sid, room_id))

        with self._memory_lock:
            return self._memory.get(sid, {}).get(room_id)

    # チャットルームが存在するかどうかを確認します。
    # Check whether the chat room exists.
    def room_exists(self, sid: str, room_id: str) -> bool:
        return self.get_room(sid, room_id) is not None

    # Redisからルームを読み出し、壊れている/期限切れなら削除して None を返します。
    # Read a room from Redis, deleting and returning None when it is corrupted or expired.
    def _read_room_from_redis(self, reader, key: str) -> dict | None:
        payload = reader.get(key)
        if not payload:
            return None
        room = self._decode(payload)
        if not room:
            reader.delete(key)
            return None
        if self._is_expired(room):
            reader.delete(key)
            return None
        return room

    # 更新されたルームをRedisへ書き戻します（期限切れなら保存せず削除）。
    # Write the updated room back to Redis (delete instead of saving once expired).
    def _write_room_to_redis(self, writer, key: str, room: dict) -> bool:
        # 書き込みは利用中の証拠なので、保存のたびに有効期限の起点を更新する。
        # A write means the room is in use, so refresh the expiry baseline on save.
        room["last_active_at"] = datetime.now().isoformat()
        # Redis では残TTLを再計算して保存し、期限切れなら保存せず削除する
        # Recalculate remaining TTL for Redis; delete instead of saving when expired.
        ttl = self._remaining_ttl(room)
        if ttl <= 0:
            writer.delete(key)
            return False
        writer.set(key, self._encode(room), ex=ttl)
        return True

    # WATCH/MULTI/EXEC を扱えるパイプラインを返します（非対応クライアントでは None）。
    # Return a pipeline able to run WATCH/MULTI/EXEC, or None for clients without that support.
    def _watch_pipeline(self, redis_client):
        factory = getattr(redis_client, "pipeline", None)
        if factory is None:
            return None
        pipeline = factory()
        if hasattr(pipeline, "watch") and hasattr(pipeline, "multi"):
            return pipeline
        reset = getattr(pipeline, "reset", None)
        if reset is not None:
            reset()
        return None

    # ルームの read-modify-write を排他的に実行します。
    # Run a read-modify-write against a single room under mutual exclusion.
    def _mutate_room(self, sid: str, room_id: str, mutate: RoomMutation) -> bool:
        # 同一プロセス内の書き込みはルーム単位ロックで直列化し、Redis 利用時はさらに
        # WATCH/MULTI/EXEC の楽観ロックで他ワーカーからの同時更新にも備える。
        # Serialize same-process writers with a per-room lock and, on Redis, add
        # WATCH/MULTI/EXEC so writers in other workers cannot clobber each other.
        with self._room_locks.get(self._key(sid, room_id)):
            redis_client = self._get_redis()
            if redis_client is not None:
                return self._mutate_room_in_redis(redis_client, sid, room_id, mutate)
            return self._mutate_room_in_memory(sid, room_id, mutate)

    # メモリ実装のルームをロック下で更新します。
    # Update an in-memory room while holding the memory lock.
    def _mutate_room_in_memory(self, sid: str, room_id: str, mutate: RoomMutation) -> bool:
        with self._memory_lock:
            room = self._memory.get(sid, {}).get(room_id)
            if not room:
                return False
            if not mutate(room):
                return False
            room["last_active_at"] = datetime.now().isoformat()
            self._memory.setdefault(sid, {})[room_id] = room
            return True

    # Redis上のルームを楽観ロック付きで更新します。
    # Update a room stored in Redis using optimistic locking.
    def _mutate_room_in_redis(self, redis_client, sid: str, room_id: str, mutate: RoomMutation) -> bool:
        key = self._key(sid, room_id)
        for _ in range(MAX_ROOM_MUTATION_ATTEMPTS):
            pipeline = self._watch_pipeline(redis_client)
            # WATCH 非対応のクライアントではプロセス内ロックだけで保護する。
            # Clients without WATCH support rely on the in-process lock alone.
            if pipeline is None:
                return self._mutate_room_without_watch(redis_client, key, mutate)
            with pipeline:
                try:
                    pipeline.watch(key)
                    room = self._read_room_from_redis(pipeline, key)
                    if not room:
                        return False
                    if not mutate(room):
                        pipeline.unwatch()
                        return False
                    pipeline.multi()
                    saved = self._write_room_to_redis(pipeline, key, room)
                    pipeline.execute()
                except WatchError:
                    # 読み出しから書き戻しの間に別の書き込みが入ったので、最新状態からやり直す。
                    # Another writer landed between the read and the write-back, so retry from fresh state.
                    logger.debug("Retrying ephemeral room update after a concurrent write.")
                    continue
                return saved
        logger.warning("Gave up updating an ephemeral room after repeated write conflicts.")
        return False

    # 楽観ロックを使えない場合の read-modify-write です。
    # Read-modify-write used when optimistic locking is unavailable.
    def _mutate_room_without_watch(self, redis_client, key: str, mutate: RoomMutation) -> bool:
        room = self._read_room_from_redis(redis_client, key)
        if not room:
            return False
        if not mutate(room):
            return False
        return self._write_room_to_redis(redis_client, key, room)

    # 指定されたチャットルームを削除します。
    # Delete the specified chat room.
    def delete_room(self, sid: str, room_id: str) -> bool:
        # Redisが利用可能であれば、Redisからルームを削除します。
        # If Redis is available, delete the room from Redis.
        # 追記中のルームを消さないよう、更新と同じルーム単位ロックの下で削除する。
        # Delete under the same per-room lock as updates so an in-flight append is not interleaved.
        with self._room_locks.get(self._key(sid, room_id)):
            redis_client = self._get_redis()
            if redis_client is not None:
                return redis_client.delete(self._key(sid, room_id)) > 0

            # オンメモリの場合、セッション内の指定ルームを削除し、必要に応じてセッションキー自体も削除します。
            # For in-memory mode, delete the specified room from the session and cleanup the session key if empty.
            with self._memory_lock:
                rooms = self._memory.get(sid)
                if not rooms or room_id not in rooms:
                    return False
                del rooms[room_id]
                if not rooms:
                    del self._memory[sid]
                return True

    # 指定されたユーザーメッセージ数よりも前のメッセージ履歴を削除します。
    # Delete message history prior to the specified trailing user message count.
    def delete_messages_from_trailing_user_count(self, sid: str, room_id: str, trailing_user_count: int) -> bool:
        """Delete messages from the user message that has `trailing_user_count` user messages after it."""

        # 日本語: 読み出し直後の履歴に対して切り詰めを適用します。
        # English: Apply the trim to the history as it was read inside the lock.
        def trim(room: dict) -> bool:
            messages = room.get("messages") or []
            user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
            # ユーザーメッセージ数が指定数以下の場合は削除を行いません。
            # Do not delete if the number of user messages is less than or equal to the trailing count.
            if len(user_indices) <= trailing_user_count:
                return False
            target_msg_index = user_indices[len(user_indices) - 1 - trailing_user_count]
            room["messages"] = messages[:target_msg_index]
            return True

        return self._mutate_room(sid, room_id, trim)

    # 最後のAIアシスタントメッセージ（およびそれ以降のメッセージ）を削除します。
    # Remove the last assistant message (and any messages following it).
    def delete_last_assistant_message(self, sid: str, room_id: str) -> bool:
        """Delete the last assistant message (and any messages after it) from an ephemeral room."""

        # 日本語: 最後のアシスタント発話以降を切り落とします。
        # English: Cut everything from the last assistant message onwards.
        def trim(room: dict) -> bool:
            messages = room.get("messages") or []
            last_idx = -1
            # メッセージ履歴を末尾から走査して、最後のアシスタントメッセージのインデックスを特定します。
            # Scan message history from the end to identify the last assistant message index.
            for i, message in enumerate(messages):
                if message.get("role") == "assistant":
                    last_idx = i
            if last_idx < 0:
                return False
            room["messages"] = messages[:last_idx]
            return True

        return self._mutate_room(sid, room_id, trim)

    # 返答が付かなかった末尾のユーザー発話を取り除きます（ルーム自体は残します）。
    # Remove the trailing user messages that never got a reply (the room is kept).
    def delete_unanswered_user_messages(self, sid: str, room_id: str) -> bool:
        # 日本語: 末尾の未回答ユーザー発話だけを切り落とします。
        # English: Trim only the trailing run of unanswered user messages.
        def trim(room: dict) -> bool:
            messages = room.get("messages") or []
            # 末尾から連続するユーザー発話だけを切り落とす。ルームを削除してしまうと
            # 画面を開いたままのクライアントが以後 404 になり会話を続けられない。
            # Trim only the trailing run of user messages. Deleting the room would
            # make every later request from the still-open client fail with 404.
            end = len(messages)
            while end > 0 and messages[end - 1].get("role") == "user":
                end -= 1
            if end == len(messages):
                return False

            room["messages"] = messages[:end]
            return True

        return self._mutate_room(sid, room_id, trim)

    # ルームのタイトルを変更します。
    # Rename the chat room title.
    def rename_room(self, sid: str, room_id: str, new_title: str) -> bool:
        # 日本語: タイトルだけを差し替えます。
        # English: Replace only the room title.
        def rename(room: dict) -> bool:
            room["title"] = new_title
            return True

        return self._mutate_room(sid, room_id, rename)

    # ルームに新しいメッセージ（および添付ファイル情報）を追加します。
    # Append a new message (along with optional attachment metadata) to the room.
    def append_message(
        self,
        sid: str,
        room_id: str,
        role: str,
        content: str,
        message_parts: list[dict] | None = None,
        attached_file_contents: list | None = None,
        web_search_context: list[dict] | None = None,
    ) -> bool:
        # 指定ルームへメッセージを追記して永続化する
        # Append a message to the room and persist updated state.
        entry = {"role": role, "content": content}
        # メッセージパーツや添付ファイルがある場合は追加のメタデータに含めます。
        # Include additional metadata if message parts or file attachments exist.
        if message_parts:
            entry["message_parts"] = message_parts
        # 過去ターンで参照できるようWeb検索結果を保存する。
        # Persist web search results so later turns can reference them.
        if web_search_context:
            entry["web_search_context"] = web_search_context
        if attached_file_contents:
            encoded_attached_files = encode_attached_files_for_storage(attached_file_contents)
            if encoded_attached_files:
                entry["attached_file_contents"] = json.loads(encoded_attached_files)

        # 追記はロック内で読み直した履歴に対して行う。生成ワーカースレッドとユーザー操作が
        # 重なったとき、外で読んだ履歴に追記すると相手の追記を丸ごと上書きしてしまう。
        # Append to the history re-read inside the lock: appending to a copy read
        # earlier would overwrite whatever the other writer stored in the meantime.
        def append(room: dict) -> bool:
            messages = room.get("messages") or []
            messages.append(entry)
            room["messages"] = messages
            return True

        return self._mutate_room(sid, room_id, append)

    # 指定されたルームのメッセージ履歴リストを取得します。
    # Retrieve the list of messages in the specified room.
    def get_messages(self, sid: str, room_id: str) -> list:
        room = self.get_room(sid, room_id)
        # ルームが存在しない場合は空リストを返します。
        # Return an empty list if the room does not exist.
        if not room:
            return []
        return room.get("messages") or []
