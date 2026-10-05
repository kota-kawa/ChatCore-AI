import unittest
from unittest.mock import AsyncMock, patch

from services.memo_trash_cleanup import cleanup_expired_memo_trash


class MemoTrashCleanupTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_returns_the_number_of_purged_memos(self):
        purge = AsyncMock(return_value=4)
        with patch("services.memo_trash_cleanup.purge_expired_memo_trash", new=purge):
            self.assertEqual(await cleanup_expired_memo_trash(), 4)

        purge.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
