import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from services.ephemeral_store import EphemeralChatStore


class DummyRedis:
    def __init__(self):
        self.store = {}
        self.expiry = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        if ex is not None:
            self.expiry[key] = ex
        return True

    def delete(self, key):
        if key in self.store:
            del self.store[key]
            return 1
        return 0


class EphemeralChatStoreMemoryTest(unittest.TestCase):
    def test_memory_flow(self):
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

    def test_memory_created_at_is_iso_string(self):
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")

            room = store.get_room("sid", "room")

            self.assertIsInstance(room["created_at"], str)
            self.assertIsNotNone(datetime.fromisoformat(room["created_at"]))

    def test_memory_cleanup_expires_rooms(self):
        with patch("services.ephemeral_store.get_redis_client", return_value=None):
            store = EphemeralChatStore(expiration_seconds=10)
            store.create_room("sid", "room", "title")
            store._memory["sid"]["room"]["created_at"] = datetime.now() - timedelta(seconds=20)

            store.cleanup()

            self.assertFalse(store.room_exists("sid", "room"))

    def test_redis_created_at_is_iso_string(self):
        dummy_redis = DummyRedis()
        with patch("services.ephemeral_store.get_redis_client", return_value=dummy_redis):
            store = EphemeralChatStore(expiration_seconds=60)
            store.create_room("sid", "room", "title")

            room = store.get_room("sid", "room")

            self.assertIsInstance(room["created_at"], str)
            self.assertIsNotNone(datetime.fromisoformat(room["created_at"]))

    def test_redis_corrupted_payload_returns_none_and_deletes_key(self):
        dummy_redis = DummyRedis()
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
