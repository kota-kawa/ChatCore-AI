import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import (
    _compose_task_prompt_template,
    add_bookmark,
    add_prompt_as_task,
    remove_bookmark,
)
from tests.helpers.request_helpers import build_request


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
def make_request(method, path, payload, session=None):
    return build_request(
        method=method,
        path=path,
        json_body=payload,
        session=session,
    )


# 日本語: PromptBookmarkApiTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptBookmarkApiTestCase.
class PromptBookmarkApiTestCase(unittest.TestCase):
    # 日本語: test add bookmark uses prompt id without requiring content のテスト検証を担当します。
    # English: Handle verifying test behavior for test add bookmark uses prompt id without requiring content.
    def test_add_bookmark_uses_prompt_id_without_requiring_content(self):
        request = make_request(
            "POST",
            "/prompt_share/api/bookmark",
            {"prompt_id": 10},
            session={"user_id": 5},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.prompt_share.prompt_share_api._add_bookmark_for_user",
            return_value=({"message": "ブックマークが保存されました。"}, 201),
        ) as mock_add:
            response = asyncio.run(add_bookmark(request))

        self.assertEqual(response.status_code, 201)
        mock_add.assert_called_once_with(5, 10)

    # 日本語: test add bookmark rejects missing prompt id のテスト検証を担当します。
    # English: Handle verifying test behavior for test add bookmark rejects missing prompt id.
    def test_add_bookmark_rejects_missing_prompt_id(self):
        request = make_request(
            "POST",
            "/prompt_share/api/bookmark",
            {},
            session={"user_id": 5},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.prompt_share.prompt_share_api._add_bookmark_for_user") as mock_add:
            response = asyncio.run(add_bookmark(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "必要なフィールドが不足しています")
        mock_add.assert_not_called()

    # 日本語: test remove bookmark uses prompt id のテスト検証を担当します。
    # English: Handle verifying test behavior for test remove bookmark uses prompt id.
    def test_remove_bookmark_uses_prompt_id(self):
        request = make_request(
            "DELETE",
            "/prompt_share/api/bookmark",
            {"prompt_id": 10},
            session={"user_id": 5},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.prompt_share.prompt_share_api._remove_bookmark_for_user",
            return_value=1,
        ) as mock_remove:
            response = asyncio.run(remove_bookmark(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["bookmarked"])
        mock_remove.assert_called_once_with(5, 10)

    # 日本語: test add prompt as task uses separate endpoint のテスト検証を担当します。
    # English: Handle verifying test behavior for test add prompt as task uses separate endpoint.
    def test_add_prompt_as_task_uses_separate_endpoint(self):
        request = make_request(
            "POST",
            "/prompt_share/api/task",
            {"prompt_id": 10},
            session={"user_id": 5},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.prompt_share.prompt_share_api._add_prompt_as_task_for_user",
            return_value=({"message": "タスクとして追加しました。"}, 201),
        ) as mock_add:
            response = asyncio.run(add_prompt_as_task(request))

        self.assertEqual(response.status_code, 201)
        mock_add.assert_called_once_with(5, 10)

    # 日本語: test compose task prompt template keeps skill body and script のテスト検証を担当します。
    # English: Handle verifying test behavior for test compose task prompt template keeps skill body and script.
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
