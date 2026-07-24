import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import (
    _compose_task_prompt_template,
    add_prompt_as_task,
    remove_prompt_as_task,
)
from tests.helpers.request_helpers import build_request


# プロンプトをチャットで使うためのAPIテスト用HTTPリクエストを構築します。
# Build a mock HTTP request for testing prompt use-in-chat API endpoints.
def make_request(method, path, payload, session=None):
    return build_request(
        method=method,
        path=path,
        json_body=payload,
        session=session,
    )


class PromptUseInChatApiTestCase(unittest.TestCase):
    # 共有プロンプトを「チャットで使う」ための追加処理が、専用のエンドポイントを通じて実行できることを検証します。
    # Verify that adding a prompt for chat use goes through the dedicated task-creation endpoint.
    def test_add_prompt_as_task_uses_separate_endpoint(self):
        request = make_request(
            "POST",
            "/prompt_share/api/task",
            {"prompt_id": 10},
            session={"user_id": 5},
        )

        # タスク追加ヘルパーの戻り値をモック
        # Mock the helper response for adding a prompt as a task
        with patch(
            "blueprints.prompt_share.prompt_share_api._add_prompt_as_task_for_user",
            return_value=({"message": "チャットで使えるように追加しました。", "used_in_chat": True}, 201),
        ) as mock_add:
            response = asyncio.run(add_prompt_as_task(request))

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["used_in_chat"])
        mock_add.assert_called_once_with(5, 10)

    # 共有プロンプトの「チャットで使う」状態を解除する処理が、専用エンドポイントから実行できることを検証します。
    # Verify that removing a prompt from chat use goes through the dedicated task-removal endpoint.
    def test_remove_prompt_as_task_uses_separate_endpoint(self):
        request = make_request(
            "DELETE",
            "/prompt_share/api/task",
            {"prompt_id": 10},
            session={"user_id": 5},
        )

        with patch(
            "blueprints.prompt_share.prompt_share_api._remove_prompt_as_task_for_user",
            return_value=({"message": "チャットで使う設定を解除しました。", "used_in_chat": False}, 200),
        ) as mock_remove:
            response = asyncio.run(remove_prompt_as_task(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["used_in_chat"])
        mock_remove.assert_called_once_with(5, 10)

    # SKILLからタスク用テンプレートを生成する際、Markdownと複数の名前付きリソースを維持することを検証します。
    # Verify that composing a task template preserves Markdown and named resources.
    def test_compose_task_prompt_template_keeps_skill_body_and_resources(self):
        template = _compose_task_prompt_template(
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
        template = _compose_task_prompt_template(
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
