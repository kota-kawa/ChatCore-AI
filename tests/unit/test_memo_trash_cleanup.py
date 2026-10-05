import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.memo_trash_cleanup import MAX_PURGE_BATCHES_PER_CYCLE, cleanup_expired_memo_trash
from services.repositories.memo_constants import MEMO_TRASH_PURGE_BATCH_SIZE


class MemoTrashCleanupTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_returns_the_number_of_purged_memos(self):
        purge = AsyncMock(return_value=4)
        with patch("services.memo_trash_cleanup.purge_expired_memo_trash", new=purge):
            self.assertEqual(await cleanup_expired_memo_trash(), 4)

        purge.assert_awaited_once_with(limit=MEMO_TRASH_PURGE_BATCH_SIZE)

    async def test_cleanup_keeps_purging_full_batches_up_to_the_cycle_cap(self):
        purge = AsyncMock(return_value=MEMO_TRASH_PURGE_BATCH_SIZE)
        with patch("services.memo_trash_cleanup.purge_expired_memo_trash", new=purge):
            total = await cleanup_expired_memo_trash()

        self.assertEqual(purge.await_count, MAX_PURGE_BATCHES_PER_CYCLE)
        self.assertEqual(total, MEMO_TRASH_PURGE_BATCH_SIZE * MAX_PURGE_BATCHES_PER_CYCLE)

    async def test_cleanup_stops_after_a_partial_batch(self):
        purge = AsyncMock(side_effect=[MEMO_TRASH_PURGE_BATCH_SIZE, 7, 99])
        with patch("services.memo_trash_cleanup.purge_expired_memo_trash", new=purge):
            total = await cleanup_expired_memo_trash()

        self.assertEqual(purge.await_count, 2)
        self.assertEqual(total, MEMO_TRASH_PURGE_BATCH_SIZE + 7)


class PeriodicCleanupIsolationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_failing_memo_trash_purge_does_not_skip_the_other_cleanups(self):
        try:
            import app as app_module
        except Exception as exc:  # the app needs its runtime environment to import
            self.skipTest(f"app cannot be imported here: {exc}")

        stop_event = asyncio.Event()

        async def last_cleanup(_ids):
            stop_event.set()

        chat_images = AsyncMock(side_effect=last_cleanup)
        attachments = AsyncMock()
        avatars = AsyncMock()
        with patch.object(app_module, "try_acquire_single_flight", return_value=True), patch.object(
            app_module, "cleanup_expired_memo_trash", new=AsyncMock(side_effect=RuntimeError("db down"))
        ), patch.object(app_module, "cleanup_ephemeral_chats", new=MagicMock()), patch.object(
            app_module, "cleanup_orphaned_prompt_attachments", new=attachments
        ), patch.object(app_module, "cleanup_orphaned_avatars", new=avatars), patch.object(
            app_module, "cleanup_orphaned_chat_images", new=chat_images
        ), patch.object(app_module.ephemeral_store, "list_referenced_image_ids", return_value=set()):
            await asyncio.wait_for(app_module.periodic_cleanup(stop_event), timeout=5)

        attachments.assert_awaited_once()
        avatars.assert_awaited_once()
        chat_images.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
