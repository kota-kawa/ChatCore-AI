"""チャットのタスク編集・削除ヘルパーが、非同期のタスクサービスへ所有者のユーザー ID つきで委譲することを検証するテスト。

Tests that the chat task edit and delete helpers delegate to the async task service with the owner's user id.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.chat.tasks import _delete_task_for_user, _edit_task_for_user


# blueprints.chat.tasks の _delete_task_for_user と _edit_task_for_user が、サービスの呼び出し境界を保つことを確かめる。
# Checks _delete_task_for_user and _edit_task_for_user in blueprints.chat.tasks keep the service call boundary.
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
