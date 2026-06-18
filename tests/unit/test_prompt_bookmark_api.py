import asyncio
import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import (
    _compose_task_prompt_template,
    add_prompt_as_task,
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
            return_value=({"message": "タスクとして追加しました。"}, 201),
        ) as mock_add:
            response = asyncio.run(add_prompt_as_task(request))

        self.assertEqual(response.status_code, 201)
        mock_add.assert_called_once_with(5, 10)

    # スキル型プロンプトからタスク用テンプレートを生成する際、説明文やPythonスクリプトが欠落せず維持されることを検証します。
    # Verify that composing a task template from a skill-type prompt preserves both description markdown and Python script.
    def test_compose_task_prompt_template_keeps_skill_body_and_script(self):
        template = _compose_task_prompt_template(
            {
                "prompt_type": "skill",
                "content": "",
                "skill_markdown": "# SKILL\n\n使い方",
                "skill_python_script": "print('hello')",
            }
        )

        self.assertIn("# SKILL", template)
        self.assertIn("```python\nprint('hello')\n```", template)


if __name__ == "__main__":
    unittest.main()
