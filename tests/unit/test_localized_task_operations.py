import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.chat.tasks import _delete_task_for_user, _edit_task_for_user


class LocalizedTaskOperationsTestCase(unittest.TestCase):
    def test_delete_uses_async_task_service_with_owned_id(self):
        with patch(
            "blueprints.chat.tasks.delete_task_record",
            new=AsyncMock(),
        ) as delete_task:
            asyncio.run(_delete_task_for_user(7, 42))

        delete_task.assert_awaited_once_with(7, 42)

    def test_editing_system_task_preserves_service_boundary(self):
        with patch(
            "blueprints.chat.tasks.edit_task_record",
            new=AsyncMock(return_value=True),
        ) as edit_task:
            updated = asyncio.run(
                _edit_task_for_user(
                    7,
                    42,
                    "My topic helper",
                    "Custom prompt",
                    "",
                    "",
                    "",
                    "",
                )
            )

        self.assertTrue(updated)
        edit_task.assert_awaited_once_with(7, 42, "My topic helper", "Custom prompt", "", "", "", "")


if __name__ == "__main__":
    unittest.main()
