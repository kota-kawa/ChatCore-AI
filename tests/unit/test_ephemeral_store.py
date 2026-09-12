import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from services.ephemeral_store import EphemeralChatStore


# 日本語: テスト用の擬似Dummy Redisクラスです。
# English: Mock Dummy Redis class for testing.
class DummyRedis:
    def __init__(self):
        self.store = {}
        self.expiry = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if ex is not None:
            self.expiry[key] = ex
        return True

    def delete(self, key):
        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if key in self.store:
            del self.store[key]
            return 1
        return 0


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


if __name__ == "__main__":
    unittest.main()
