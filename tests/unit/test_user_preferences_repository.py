import unittest
from unittest.mock import AsyncMock, patch

from services.chat_service import get_user_preferred_locale, update_user_preferred_locale


class UserPreferencesRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_get_returns_normalized_saved_locale(self):
        with patch("services.chat_service._read", new=AsyncMock(return_value="en")) as read:
            self.assertEqual(await get_user_preferred_locale(7), "en")
        read.assert_awaited_once()

    async def test_update_commits_existing_user(self):
        with patch("services.chat_service._write", new=AsyncMock(return_value=True)) as write:
            self.assertTrue(await update_user_preferred_locale(7, "en"))
        write.assert_awaited_once()

    async def test_update_rolls_back_missing_user(self):
        with patch("services.chat_service._write", new=AsyncMock(return_value=False)) as write:
            self.assertFalse(await update_user_preferred_locale(99, "ja"))
        write.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
