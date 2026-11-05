"""タスクとプロンプトの削除が、行を物理削除せず削除済みとして印を付ける（論理削除）サービスを通ることを検証するテスト。

Tests that deleting a task or a prompt goes through services that soft-delete the row (mark it deleted) rather than removing it.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from blueprints.chat.tasks import _delete_task_for_user
from blueprints.prompt_share.prompt_manage_api import _delete_prompt_for_user


# 削除用の内部関数が非同期サービスへ委譲することを検証するテストクラス。
# Test class verifying that the internal delete helpers delegate to the async services.
class SoftDeleteQueryTestCase(unittest.TestCase):
    def test_delete_task_marks_row_deleted_through_async_service(self):
        with patch("blueprints.chat.tasks.delete_task_record", new=AsyncMock()) as delete_task:
            asyncio.run(_delete_task_for_user(5, 41))

        delete_task.assert_awaited_once_with(5, 41)

    def test_delete_prompt_marks_prompt_row_deleted_through_service(self):
        service = MagicMock()
        service.delete_prompt = AsyncMock(return_value=([], 1))

        with patch("blueprints.prompt_share.prompt_manage_api._service", return_value=service):
            deleted = asyncio.run(_delete_prompt_for_user(8, 77))

        self.assertEqual(deleted, 1)
        service.delete_prompt.assert_awaited_once_with(user_id=8, prompt_id=77)


if __name__ == "__main__":
    unittest.main()
