import asyncio
import unittest

from blueprints.chat.tasks import _fetch_tasks_from_db
from services.default_tasks import load_default_tasks


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
