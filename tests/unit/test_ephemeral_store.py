import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from services.ephemeral_store import EphemeralChatStore


# 日本語: テスト用の擬似Dummy Redisクラスです。
# English: Mock Dummy Redis class for testing.
class DummyRedis:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        self.store = {}
        self.expiry = {}

    # 日本語: get の取得処理を担当します。
    # English: Handle fetching for get.
    def get(self, key):
        return self.store.get(key)

    # 日本語: set の設定処理を担当します。
    # English: Handle setting for set.
    def set(self, key, value, ex=None):
        self.store[key] = value
        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if ex is not None:
            self.expiry[key] = ex
        return True

    # 日本語: delete の削除処理を担当します。
    # English: Handle deleting for delete.
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
            store._memory["sid"]["room"]["created_at"] = datetime.now() - timedelta(seconds=20)

            store.cleanup()

            self.assertFalse(store.room_exists("sid", "room"))

    # 日本語: deleteroomifなしassistantmessages削除するユーザーonlyroomことを検証します。
    # English: Verify that delete room if no assistant messages deletes user only room.
    def test_delete_room_if_no_assistant_messages_deletes_user_only_room(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")
            store.append_message("sid", "room", "user", "hello")

            deleted = store.delete_room_if_no_assistant_messages("sid", "room")

            self.assertTrue(deleted)
            self.assertFalse(store.room_exists("sid", "room"))

    # 日本語: assistantreplyを使用する場合、deleteroomifなしassistantmessages保持するroomことを検証します。
    # English: Verify that delete room if no assistant messages keeps room with assistant reply.
    def test_delete_room_if_no_assistant_messages_keeps_room_with_assistant_reply(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")
            store.append_message("sid", "room", "user", "hello")
            store.append_message("sid", "room", "assistant", "hi")

            deleted = store.delete_room_if_no_assistant_messages("sid", "room")

            self.assertFalse(deleted)
            self.assertTrue(store.room_exists("sid", "room"))

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


if __name__ == "__main__":
    unittest.main()
