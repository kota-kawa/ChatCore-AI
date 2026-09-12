import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from services.ephemeral_store import EphemeralChatStore, WatchError


# 日本語: 擬似Redisの WATCH/MULTI/EXEC を再現するパイプラインです。
# English: Fake pipeline reproducing Redis WATCH/MULTI/EXEC semantics.
class DummyRedisPipeline:
    def __init__(self, redis_client):
        self._redis = redis_client
        self._watched = {}
        self._queued = []
        self._buffering = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        self.reset()
        return False

    # 日本語: 監視状態とキュー済みコマンドを破棄します。
    # English: Discard watched revisions and queued commands.
    def reset(self):
        self._watched = {}
        self._queued = []
        self._buffering = False

    # 日本語: キーの現在のリビジョンを記録して監視を開始します。
    # English: Start watching a key by recording its current revision.
    def watch(self, key):
        self._watched[key] = self._redis.revision(key)

    def unwatch(self):
        self._watched = {}

    # 日本語: 以降のコマンドをトランザクションとしてキューします。
    # English: Queue subsequent commands as a transaction.
    def multi(self):
        self._buffering = True

    def get(self, key):
        return self._redis.get(key)

    def set(self, key, value, ex=None):
        # 日本語: MULTI 後はキューし、それ以前は即時実行します。
        # English: Queue after MULTI, execute immediately before it.
        if self._buffering:
            self._queued.append(("set", key, value, ex))
            return self
        return self._redis.set(key, value, ex=ex)

    def delete(self, key):
        # 日本語: MULTI 後はキューし、それ以前は即時実行します。
        # English: Queue after MULTI, execute immediately before it.
        if self._buffering:
            self._queued.append(("delete", key, None, None))
            return self
        return self._redis.delete(key)

    # 日本語: 監視キーが変化していれば WatchError、変化なしならキューを実行します。
    # English: Raise WatchError when a watched key changed, otherwise run the queue.
    def execute(self):
        for key, revision in self._watched.items():
            if self._redis.revision(key) != revision:
                self.reset()
                raise WatchError("watched key changed")
        results = []
        for command, key, value, ex in self._queued:
            if command == "set":
                results.append(self._redis.set(key, value, ex=ex))
            else:
                results.append(self._redis.delete(key))
        self.reset()
        return results


# 日本語: テスト用の擬似Dummy Redisクラスです。
# English: Mock Dummy Redis class for testing.
class DummyRedis:
    def __init__(self):
        self.store = {}
        self.expiry = {}
        self.revisions = {}
        # 日本語: 読み出し直後に別の書き込みを差し込むためのフックです。
        # English: Hook used to interleave another write right after a read.
        self.after_get = None

    # 日本語: キーの書き込み回数を返します（楽観ロックの判定に使用）。
    # English: Return the write counter of a key (used for optimistic-lock checks).
    def revision(self, key):
        return self.revisions.get(key, 0)

    def get(self, key):
        # 日本語: 読み手が見た時点のスナップショットを返し、その後に割り込み書き込みを走らせます。
        # English: Return the snapshot the reader saw, then let the interleaved write run.
        value = self.store.get(key)
        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if self.after_get is not None:
            self.after_get(key)
        return value

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.revisions[key] = self.revision(key) + 1
        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if ex is not None:
            self.expiry[key] = ex
        return True

    def delete(self, key):
        self.revisions[key] = self.revision(key) + 1
        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if key in self.store:
            del self.store[key]
            return 1
        return 0

    def pipeline(self):
        return DummyRedisPipeline(self)


# 日本語: EphemeralChatStoreMemoryTest のテストケースをまとめます。
# English: Group test cases for EphemeralChatStoreMemoryTest.
class EphemeralChatStoreMemoryTest(unittest.TestCase):
    # 日本語: memoryフローことを検証します。
    # English: Verify that memory flow.
    def test_memory_flow(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")

            self.assertTrue(store.room_exists("sid", "room"))

            store.append_message("sid", "room", "user", "hello")
            messages = store.get_messages("sid", "room")
            self.assertEqual(messages[0]["role"], "user")
            self.assertEqual(messages[0]["content"], "hello")

            self.assertTrue(store.rename_room("sid", "room", "new"))
            room = store.get_room("sid", "room")
            self.assertEqual(room["title"], "new")

            self.assertTrue(store.delete_room("sid", "room"))
            self.assertFalse(store.room_exists("sid", "room"))

    # 日本語: memorycreatedatがisostringことを検証します。
    # English: Verify that memory created at is iso string.
    def test_memory_created_at_is_iso_string(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")

            room = store.get_room("sid", "room")

            self.assertIsInstance(room["created_at"], str)
            self.assertIsNotNone(datetime.fromisoformat(room["created_at"]))

    # 日本語: memoryクリーンアップexpiresルームことを検証します。
    # English: Verify that memory cleanup expires rooms.
    def test_memory_cleanup_expires_rooms(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=10)
            store.create_room("sid", "room", "title")
            stale = (datetime.now() - timedelta(seconds=20)).isoformat()
            store._memory["sid"]["room"]["created_at"] = stale
            store._memory["sid"]["room"]["last_active_at"] = stale

            store.cleanup()

            self.assertFalse(store.room_exists("sid", "room"))

    # 日本語: 会話が続いている間はルームの有効期限が延長されることを検証します。
    # English: Verify that an actively used room has its expiry extended.
    def test_memory_activity_extends_expiration(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=10)
            store.create_room("sid", "room", "title")
            store._memory["sid"]["room"]["created_at"] = (
                datetime.now() - timedelta(seconds=20)
            ).isoformat()

            # 利用（メッセージ追加）で最終利用時刻が更新され、期限切れにならない。
            # Using the room refreshes the last-activity timestamp, so it survives.
            store.append_message("sid", "room", "user", "hello")
            store.cleanup()

            self.assertTrue(store.room_exists("sid", "room"))

    # 日本語: 返答が付かなかったユーザー発話だけを取り除き、ルームは残すことを検証します。
    # English: Verify that only the unanswered user message is removed and the room is kept.
    def test_delete_unanswered_user_messages_keeps_room(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")
            store.append_message("sid", "room", "user", "hello")

            discarded = store.delete_unanswered_user_messages("sid", "room")

            self.assertTrue(discarded)
            # ルームが残るので、ユーザーはそのまま会話を続けられる。
            # The room survives so the user can keep chatting in it.
            self.assertTrue(store.room_exists("sid", "room"))
            self.assertEqual(store.get_messages("sid", "room"), [])

    # 日本語: 回答済みのターンは削除されないことを検証します。
    # English: Verify that answered turns are left untouched.
    def test_delete_unanswered_user_messages_keeps_answered_turns(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")
            store.append_message("sid", "room", "user", "hello")
            store.append_message("sid", "room", "assistant", "hi")

            discarded = store.delete_unanswered_user_messages("sid", "room")

            self.assertFalse(discarded)
            self.assertEqual(len(store.get_messages("sid", "room")), 2)

    # 日本語: 直近の未回答発話だけを取り除き、過去のやり取りは残すことを検証します。
    # English: Verify that only the latest unanswered message is trimmed.
    def test_delete_unanswered_user_messages_trims_only_trailing_messages(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")
            store.append_message("sid", "room", "user", "hello")
            store.append_message("sid", "room", "assistant", "hi")
            store.append_message("sid", "room", "user", "again")

            discarded = store.delete_unanswered_user_messages("sid", "room")

            self.assertTrue(discarded)
            messages = store.get_messages("sid", "room")
            self.assertEqual([m["role"] for m in messages], ["user", "assistant"])

    # 日本語: rediscreatedatがisostringことを検証します。
    # English: Verify that redis created at is iso string.
    def test_redis_created_at_is_iso_string(self):
        dummy_redis = DummyRedis()
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=dummy_redis):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")

            room = store.get_room("sid", "room")

            self.assertIsInstance(room["created_at"], str)
            self.assertIsNotNone(datetime.fromisoformat(room["created_at"]))

    # 日本語: および削除するkey、rediscorruptedペイロード返却するnoneことを検証します。
    # English: Verify that redis corrupted payload returns none and deletes key.
    def test_redis_corrupted_payload_returns_none_and_deletes_key(self):
        dummy_redis = DummyRedis()
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=dummy_redis):
            store = EphemeralChatStore(expiration_seconds=60)
            key = store._key("sid", "room")
            dummy_redis.set(key, "{invalid-json")

            with patch("services.ephemeral_store.logger.warning") as mock_warning:
                room = store.get_room("sid", "room")

            self.assertIsNone(room)
            self.assertIsNone(dummy_redis.get(key))
            mock_warning.assert_called_once()


# 日本語: Redis クライアント取得のリトライ挙動をまとめたテストです。
# English: Group test cases for Redis client acquisition retry behaviour.
class EphemeralChatStoreRedisLookupTest(unittest.TestCase):
    # 日本語: 一度 None が返ってもキャッシュせず、次回に Redis を使い直すことを検証します。
    # English: Verify a None result is not cached so the next call retries Redis.
    def test_redis_client_is_retried_after_a_miss(self):
        dummy_redis = DummyRedis()
        clients = [None, dummy_redis]

        # 日本語: 1回目は Redis 断を模して None、2回目以降はクライアントを返します。
        # English: Return None first to emulate an outage, then hand back a client.
        def fake_get_redis_client():
            return clients.pop(0) if clients else dummy_redis

        with patch(
            "services.ephemeral_store.get_redis_client",
            side_effect=fake_get_redis_client,
        ):
            store = EphemeralChatStore(expiration_seconds=60)

            # 日本語: Redis が取れない間はメモリへ退避します。
            # English: Fall back to memory while Redis is unavailable.
            store.create_room("sid", "memory-room", "title")
            self.assertEqual(dummy_redis.store, {})

            # 日本語: 復旧後は再取得され、以後の書き込みが Redis に載ります。
            # English: After recovery the client is fetched again and writes hit Redis.
            store.create_room("sid", "redis-room", "title")
            self.assertIn(store._key("sid", "redis-room"), dummy_redis.store)

    # 日本語: 取得できたクライアントは再利用され、毎回作り直さないことを検証します。
    # English: Verify an acquired client is reused instead of being rebuilt each time.
    def test_redis_client_is_cached_once_available(self):
        dummy_redis = DummyRedis()
        with patch(
            "services.ephemeral_store.get_redis_client",
            return_value=dummy_redis,
        ) as mock_get_client:
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")
            store.get_room("sid", "room")
            store.append_message("sid", "room", "user", "hello")

            mock_get_client.assert_called_once()


# 日本語: ルーム更新の排他制御に関するテストをまとめます。
# English: Group test cases covering concurrent room updates.
class EphemeralChatStoreConcurrencyTest(unittest.TestCase):
    # 日本語: 読み出しと書き戻しの間に別ワーカーが追記しても、両方のメッセージが残ることを検証します。
    # English: Verify both messages survive when another worker appends between the read and write-back.
    def test_concurrent_redis_append_keeps_both_messages(self):
        dummy_redis = DummyRedis()
        with patch("services.ephemeral_store.get_redis_client", return_value=dummy_redis):
            # 日本語: 同じ Redis を共有する別ワーカーのストアを用意します。
            # English: Prepare a second store sharing the same Redis, standing in for another worker.
            store = EphemeralChatStore(expiration_seconds=60)
            other_worker = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")

            # 日本語: 最初の読み出し直後に、別ワーカーの追記を割り込ませます。
            # English: Interleave the other worker's append right after the first read.
            def interleave_other_worker(_key):
                dummy_redis.after_get = None
                other_worker.append_message("sid", "room", "assistant", "from-other-worker")

            dummy_redis.after_get = interleave_other_worker

            self.assertTrue(store.append_message("sid", "room", "user", "from-this-worker"))

            contents = [message["content"] for message in store.get_messages("sid", "room")]
            self.assertEqual(contents, ["from-other-worker", "from-this-worker"])

    # 日本語: 複数スレッドから同時に追記しても全メッセージが残ることを検証します。
    # English: Verify every message survives simultaneous appends from multiple threads.
    def test_concurrent_threads_append_every_message(self):
        dummy_redis = DummyRedis()
        with patch("services.ephemeral_store.get_redis_client", return_value=dummy_redis):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")
            writer_count = 8
            start = threading.Barrier(writer_count)

            # 日本語: 全スレッドを同時に走らせて追記を競合させます。
            # English: Release every thread at once so the appends race.
            def writer(index):
                start.wait(timeout=5)
                store.append_message("sid", "room", "user", f"message-{index}")

            threads = [threading.Thread(target=writer, args=(index,)) for index in range(writer_count)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            contents = {message["content"] for message in store.get_messages("sid", "room")}
            self.assertEqual(contents, {f"message-{index}" for index in range(writer_count)})

    # 日本語: メモリ実装でも並行追記が失われないことを検証します。
    # English: Verify the in-memory fallback does not lose concurrent appends either.
    def test_concurrent_threads_append_every_message_in_memory(self):
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")
            writer_count = 8
            start = threading.Barrier(writer_count)

            # 日本語: 全スレッドを同時に走らせて追記を競合させます。
            # English: Release every thread at once so the appends race.
            def writer(index):
                start.wait(timeout=5)
                store.append_message("sid", "room", "user", f"message-{index}")

            threads = [threading.Thread(target=writer, args=(index,)) for index in range(writer_count)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            contents = {message["content"] for message in store.get_messages("sid", "room")}
            self.assertEqual(contents, {f"message-{index}" for index in range(writer_count)})

    # 日本語: 掃除の走査中に別スレッドがルームを作っても壊れないことを検証します。
    # English: Verify cleanup survives another thread creating a room mid-scan.
    def test_cleanup_survives_concurrent_room_creation(self):
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=60)
            for index in range(5):
                store.create_room(f"sid-{index}", "room", "title")

            scan_started = threading.Event()

            # 日本語: 走査が始まったら新しいセッションのルームを追加します。
            # English: Add a room for a brand-new session once the scan has started.
            def creator():
                scan_started.wait(timeout=5)
                store.create_room("late-sid", "room", "title")

            thread = threading.Thread(target=creator)
            thread.start()
            original_is_expired = store._is_expired

            # 日本語: 走査の各ステップで別スレッドに実行機会を与えます。
            # English: Yield to the other thread at every step of the scan.
            def slow_is_expired(room):
                scan_started.set()
                time.sleep(0.01)
                return original_is_expired(room)

            try:
                with patch.object(store, "_is_expired", side_effect=slow_is_expired):
                    store.cleanup()
            finally:
                thread.join(timeout=5)

            self.assertTrue(store.room_exists("late-sid", "room"))

    # 日本語: Redis 経路でも追記・改名・削除が従来どおり動くことを検証します。
    # English: Verify append, rename and delete still work over the Redis path.
    def test_redis_flow_still_updates_rooms(self):
        dummy_redis = DummyRedis()
        with patch("services.ephemeral_store.get_redis_client", return_value=dummy_redis):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")

            self.assertTrue(store.append_message("sid", "room", "user", "hello"))
            self.assertTrue(store.append_message("sid", "room", "assistant", "hi"))
            self.assertTrue(store.rename_room("sid", "room", "new"))
            self.assertEqual(store.get_room("sid", "room")["title"], "new")

            self.assertTrue(store.delete_last_assistant_message("sid", "room"))
            self.assertEqual([m["role"] for m in store.get_messages("sid", "room")], ["user"])

            self.assertTrue(store.delete_room("sid", "room"))
            self.assertFalse(store.room_exists("sid", "room"))

    # 日本語: 存在しないルームへの更新は False を返すことを検証します。
    # English: Verify updates against a missing room return False.
    def test_updating_missing_room_returns_false(self):
        dummy_redis = DummyRedis()
        with patch("services.ephemeral_store.get_redis_client", return_value=dummy_redis):
            store = EphemeralChatStore(expiration_seconds=60)

            self.assertFalse(store.append_message("sid", "missing", "user", "hello"))
            self.assertFalse(store.rename_room("sid", "missing", "new"))


if __name__ == "__main__":
    unittest.main()
