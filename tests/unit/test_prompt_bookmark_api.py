import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from blueprints.prompt_share.prompt_share_api import add_prompt_as_task, remove_prompt_as_task
from services.shared_content_service import SharedContentService
from tests.helpers.request_helpers import build_request


def make_request(method, path, payload, session=None):
    return build_request(
        method=method,
        path=path,
        json_body=payload,
        session=session,
    )


class PromptUseInChatApiTestCase(unittest.TestCase):
    def test_add_prompt_as_task_uses_async_service(self):
        request = make_request(
            "POST",
            "/prompt_share/api/task",
            {"prompt_id": 10},
            session={"user_id": 5},
        )
        service = MagicMock()
        service.import_prompt_as_task = AsyncMock(
            return_value=({"message": "チャットで使えるように追加しました。"}, 201)
        )

        with patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            response = asyncio.run(add_prompt_as_task(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 201)
        self.assertTrue(payload["used_in_chat"])
        service.import_prompt_as_task.assert_awaited_once_with(user_id=5, prompt_id=10)

    def test_remove_prompt_as_task_uses_async_service(self):
        request = make_request(
            "DELETE",
            "/prompt_share/api/task",
            {"prompt_id": 10},
            session={"user_id": 5},
        )
        service = MagicMock()
        service.remove_prompt_as_task = AsyncMock(
            return_value=({"message": "チャットで使う設定を解除しました。"}, 200)
        )

        with patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            response = asyncio.run(remove_prompt_as_task(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["used_in_chat"])
        service.remove_prompt_as_task.assert_awaited_once_with(user_id=5, prompt_id=10)

    def test_compose_task_prompt_template_keeps_skill_body_and_resources(self):
        template = SharedContentService._compose_task_prompt_template(
            {
                "content_format": "skill",
                "content": "",
                "attributes": {"skill_markdown": "# SKILL\n\n使い方"},
                "resources": [
                    {
                        "path": "scripts/main.py",
                        "role": "script",
                        "language": "python",
                        "content": "print('hello')",
                    },
                    {
                        "path": "config/example.json",
                        "role": "config",
                        "language": "json",
                        "content": '{"enabled": true}',
                    },
                ],
            }
        )

        self.assertIn("# SKILL", template)
        self.assertIn("## Resource: `scripts/main.py`", template)
        self.assertIn("```python\nprint('hello')\n```", template)
        self.assertIn("## Resource: `config/example.json`", template)
        self.assertIn('```json\n{"enabled": true}\n```', template)

    def test_compose_task_prompt_template_uses_safe_longer_fence(self):
        template = SharedContentService._compose_task_prompt_template(
            {
                "content_format": "skill",
                "attributes": {"skill_markdown": "# SKILL"},
                "resources": [
                    {
                        "path": "references/fences.md",
                        "language": "markdown",
                        "content": "```python\nprint('nested')\n```",
                    }
                ],
            }
        )

        self.assertIn("````markdown", template)
        self.assertIn("```python", template)


if __name__ == "__main__":
    unittest.main()
