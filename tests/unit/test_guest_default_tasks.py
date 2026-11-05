"""ゲスト（未ログイン）のタスク一覧が、共有 DB の行ではなく同梱の既定タスクから作られることを検証するテ
スト。

Tests that a guest's task list is built from the bundled default tasks rather than from shared database rows.
"""

import asyncio
import unittest

from blueprints.chat.tasks import _fetch_tasks_from_db
from services.default_tasks import load_default_tasks


# 日本語: 同梱カタログの件数、キーの重複なし、旧タスクが含まれないことを確認します。
# English: Check the catalog size, unique keys, and that retired tasks are absent.
class GuestDefaultTasksTestCase(unittest.TestCase):
    def test_guest_uses_current_bundled_catalog_without_shared_db_rows(self):
        load_default_tasks.cache_clear()
        try:
            tasks = asyncio.run(_fetch_tasks_from_db(None, "ja"))
        finally:
            load_default_tasks.cache_clear()

        keys = [task["system_task_key"] for task in tasks]
        self.assertEqual(len(tasks), 14)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(task["task_id"] is None for task in tasks))
        self.assertNotIn("🍳 レシピ", {task["name"] for task in tasks})
        self.assertNotIn("💑 デート計画", {task["name"] for task in tasks})


if __name__ == "__main__":
    unittest.main()
