import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.tasks import add_task
from blueprints.prompt_share.prompt_share_api import create_prompt
from tests.helpers.request_helpers import build_request


def make_request(path, json_body, session=None):
    return build_request(
        method="POST",
        path=path,
        json_body=json_body,
        session=session,
    )


# 日本語: Payload Validation Routesの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Payload Validation Routes.
class PayloadValidationRoutesTestCase(unittest.TestCase):
    # 日本語: stripの後、addタスク拒否するblankタイトルことを検証します。
    # English: Verify that add task rejects blank title after strip.
    def test_add_task_rejects_blank_title_after_strip(self):
        request = make_request(
            "/api/add_task",
            {"title": "   ", "prompt_content": "有効", "input_examples": "", "output_examples": ""},
            session={"user_id": 1},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.tasks._add_task_for_user") as mock_add:
            response = asyncio.run(add_task(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "タイトルとプロンプト内容は必須です。")
        mock_add.assert_not_called()

    # 日本語: createプロンプト拒否するblankタイトルことを検証します。
    # English: Verify that create prompt rejects blank title.
    def test_create_prompt_rejects_blank_title(self):
        request = make_request(
            "/prompt_share/api/prompts",
            {
                "title": "   ",
                "category": "",
                "content": "content",
                "author": "author",
            },
            session={"user_id": 1},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.prompt_share.prompt_share_api._create_prompt_for_user") as mock_create:
            response = asyncio.run(create_prompt(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "必要なフィールドが不足しています。")
        mock_create.assert_not_called()

    # 日本語: createプロンプトacceptsなしcategoryことを検証します。
    # English: Verify that create prompt accepts no category.
    def test_create_prompt_accepts_no_category(self):
        request = make_request(
            "/prompt_share/api/prompts",
            {
                "title": "title",
                "category": "",
                "content": "content",
                "author": "author",
            },
            session={"user_id": 1},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.prompt_share.prompt_share_api._create_prompt_for_user") as mock_create:
            mock_create.return_value = {"id": 1}
            response = asyncio.run(create_prompt(request))

        self.assertEqual(response.status_code, 201)
        mock_create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
