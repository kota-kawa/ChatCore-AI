import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.chat.tasks import edit_task
from tests.helpers.request_helpers import build_request


class EditDefaultTaskTestCase(unittest.TestCase):
    def test_editing_copied_default_task_uses_async_service_boundary(self):
        request = build_request(
            method="POST",
            path="/api/edit_task",
            json_body={
                "task_id": 55,
                "new_task": "Updated Task",
                "prompt_template": "Prompt",
                "response_rules": "Rules",
                "output_skeleton": "Skeleton",
                "input_examples": "input",
                "output_examples": "output",
            },
            session={"user_id": 123},
        )

        with patch(
            "blueprints.chat.tasks._edit_task_for_user",
            new=AsyncMock(return_value=True),
        ) as edit:
            response = asyncio.run(edit_task(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body)["message"], "Task updated")
        edit.assert_awaited_once_with(123, 55, "Updated Task", "Prompt", "Rules", "Skeleton", "input", "output")


if __name__ == "__main__":
    unittest.main()
