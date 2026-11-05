"""ユーザーの表示言語設定を読み書きするリポジトリ関数 (get/update_user_preferred_locale) のテスト。

Tests for the repository functions that read and write a user's preferred locale (get/update_user_preferred_locale).
"""

import unittest
from unittest.mock import AsyncMock, patch

from services.chat_service import get_user_preferred_locale, update_user_preferred_locale


# DB アクセス (_read / _write) をモックに差し替え、戻り値の受け渡しと呼び出し回数だけを確かめる。
# Replaces the DB access helpers (_read / _write) with mocks and checks only the passed-through result and call count.
class UserPreferencesRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_get_returns_normalized_saved_locale(self):
        with patch("services.chat_service._read", new=AsyncMock(return_value="en")) as read:
            self.assertEqual(await get_user_preferred_locale(7), "en")
        read.assert_awaited_once()

    async def test_update_commits_existing_user(self):
        with patch("services.chat_service._write", new=AsyncMock(return_value=True)) as write:
            self.assertTrue(await update_user_preferred_locale(7, "en"))
        write.assert_awaited_once()

    # 存在しないユーザーでは _write が False を返し、更新関数も False を返す (更新対象の行が無かったことを表す)。
    # For a missing user _write returns False and the update function returns False too (no row was updated).
    async def test_update_rolls_back_missing_user(self):
        with patch("services.chat_service._write", new=AsyncMock(return_value=False)) as write:
            self.assertFalse(await update_user_preferred_locale(99, "ja"))
        write.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
