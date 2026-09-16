import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.chat.messages import _load_task_prompt_data, _parse_task_launch_message
from blueprints.chat.tasks import (
    _add_task_for_user,
    _delete_task_for_user,
    _edit_task_for_user,
    _update_tasks_order_for_user,
    delete_task,
)
from services.api_errors import ResourceNotFoundError
from services.chat_message_normalization import find_latest_task_launch_request, mark_task_launch_input_for_llm
from tests.helpers.request_helpers import build_request


class TaskIdentityOperationsTestCase(unittest.TestCase):
    def test_reorder_delegates_to_async_repository_service(self):
        with patch(
            "blueprints.chat.tasks.update_tasks_order_record",
            new=AsyncMock(),
        ) as update_order:
            asyncio.run(_update_tasks_order_for_user(7, [3, 8]))

        update_order.assert_awaited_once_with(7, [3, 8])

    def test_delete_delegates_owned_task_id(self):
        with patch(
            "blueprints.chat.tasks.delete_task_record",
            new=AsyncMock(),
        ) as delete_record:
            asyncio.run(_delete_task_for_user(7, 99))

        delete_record.assert_awaited_once_with(7, 99)

    def test_add_and_edit_delegate_all_fields_without_dbapi_objects(self):
        with (
            patch("blueprints.chat.tasks.add_task_record", new=AsyncMock()) as add_record,
            patch("blueprints.chat.tasks.edit_task_record", new=AsyncMock(return_value=True)) as edit_record,
        ):
            asyncio.run(_add_task_for_user(7, "New", "prompt", "rules", "skeleton", "input", "output"))
            updated = asyncio.run(
                _edit_task_for_user(7, 42, "Renamed", "prompt", "rules", "skeleton", "input", "output")
            )

        self.assertTrue(updated)
        add_record.assert_awaited_once_with(7, "New", "prompt", "rules", "skeleton", "input", "output")
        edit_record.assert_awaited_once_with(7, 42, "Renamed", "prompt", "rules", "skeleton", "input", "output")

    def test_delete_route_serializes_service_error(self):
        request = build_request(
            method="POST",
            path="/api/delete_task",
            session={"user_id": 7},
            json_body={"task_id": 99},
        )
        with patch(
            "blueprints.chat.tasks._delete_task_for_user",
            new=AsyncMock(side_effect=ResourceNotFoundError("missing", code="task_not_found")),
        ):
            response = asyncio.run(delete_task(request))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.body)["code"], "task_not_found")

    def test_task_launch_parser_accepts_optional_positive_task_id(self):
        parsed = _parse_task_launch_message(
            "【タスク】同名タスク\n【タスクID】42\n【状況・作業環境】テスト"
        )
        self.assertEqual(parsed, {"task": "同名タスク", "task_id": 42, "setup_info": "テスト", "task_input": "テスト"})

    def test_prior_task_launch_is_not_active_for_a_later_user_message(self):
        messages = [
            {"role": "user", "content": "【タスク】翻訳\n【状況・作業環境】Translate this."},
            {"role": "assistant", "content": "これを翻訳して。"},
            {"role": "user", "content": "それは上に示してあるよね？"},
        ]

        self.assertIsNone(find_latest_task_launch_request(messages))
        self.assertIs(mark_task_launch_input_for_llm(messages, None), messages)

    def test_launch_input_is_labelled_only_in_the_llm_copy(self):
        messages = [{"role": "user", "content": "【タスク】翻訳\n【状況・作業環境】Translate this."}]
        request = find_latest_task_launch_request(messages)

        labelled = mark_task_launch_input_for_llm(messages, request)

        self.assertEqual(labelled[0]["content"], "【タスク】翻訳\n<task_input>\nTranslate this.\n</task_input>")
        self.assertEqual(messages[0]["content"], "【タスク】翻訳\n【状況・作業環境】Translate this.")

    def test_task_launch_loader_passes_task_id_to_async_service(self):
        with patch(
            "blueprints.chat.messages.get_task_prompt_data",
            new=AsyncMock(return_value={"name": "Task"}),
        ) as fetch:
            result = asyncio.run(_load_task_prompt_data("Task", 7, 42))

        self.assertEqual(result, {"name": "Task"})
        fetch.assert_awaited_once_with("Task", 7, 42)


if __name__ == "__main__":
    unittest.main()
