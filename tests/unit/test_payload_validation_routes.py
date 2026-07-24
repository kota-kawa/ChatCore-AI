import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.tasks import add_task
from blueprints.prompt_share.prompt_share_api import create_prompt
from tests.helpers.request_helpers import build_request


# 日本語: テスト用のPOSTリクエストを構築するヘルパー関数。
# English: Helper function to build a POST request for testing.
def make_request(path, json_body, session=None):
    return build_request(
        method="POST",
        path=path,
        json_body=json_body,
        session=session,
    )


# 日本語: 各エンドポイントのペイロードバリデーション（入力値の検証）ロジックをテストするクラス。
# English: Test class for payload validation logic across API endpoints.
class PayloadValidationRoutesTestCase(unittest.TestCase):
    # 日本語: タスク追加APIが、スペースのみのタイトルを空白として検知して400で拒否することを検証します。
    # English: Verify that the add task API rejects a whitespace-only title with a 400 error after stripping.
    def test_add_task_rejects_blank_title_after_strip(self):
        # 日本語: スペースのみのタイトルを含むリクエストを送信
        # English: Send a request with a title that contains only whitespace
        request = make_request(
            "/api/add_task",
            {"title": "   ", "prompt_content": "有効", "input_examples": "", "output_examples": ""},
            session={"user_id": 1},
        )

        # 日本語: DB書き込みをモックして検証処理の手前で止める
        # English: Mock DB write to stop execution before actual insertion
        with patch("blueprints.chat.tasks._add_task_for_user") as mock_add:
            response = asyncio.run(add_task(request))

        # 日本語: 400エラーが返り、DB書き込みが呼ばれないことを確認
        # English: Confirm 400 error and that DB write was not called
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "タイトルとプロンプト内容は必須です。")
        mock_add.assert_not_called()

    # 日本語: プロンプト作成APIが、スペースのみのタイトルを400で拒否することを検証します。
    # English: Verify that the create prompt API rejects a whitespace-only title with a 400 error.
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

        # 日本語: DB書き込みをモックして検証処理の手前で止める
        # English: Mock DB write to stop execution before actual insertion
        with patch("blueprints.prompt_share.prompt_share_api._create_prompt_for_user") as mock_create:
            response = asyncio.run(create_prompt(request))

        # 日本語: 400エラーが返り、DB書き込みが呼ばれないことを確認
        # English: Confirm 400 error and that DB write was not called
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "必要なフィールドが不足しています。")
        mock_create.assert_not_called()

    # 日本語: プロンプト作成APIが、カテゴリ未指定（空文字）のリクエストを正常に処理することを検証します。
    # English: Verify that the create prompt API accepts a request with an empty category string.
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

        # 日本語: DB書き込みをモックして201レスポンスを確認
        # English: Mock DB write and confirm 201 response
        with patch("blueprints.prompt_share.prompt_share_api._create_prompt_for_user") as mock_create:
            mock_create.return_value = {"id": 1}
            response = asyncio.run(create_prompt(request))

        # 日本語: 201 Created が返り、DB書き込みが1度呼ばれることを確認
        # English: Confirm 201 Created response and that DB write was called exactly once
        self.assertEqual(response.status_code, 201)
        mock_create.assert_called_once()

    def test_create_skill_passes_canonical_resources_to_persistence(self):
        request = make_request(
            "/prompt_share/api/prompts",
            {
                "title": "multi resource skill",
                "category": "",
                "content_format": "skill",
                "media_type": "text",
                "attributes": {"skill_markdown": "# Skill"},
                "resources": [
                    {
                        "path": "scripts/main.ts",
                        "role": "script",
                        "language": "typescript",
                        "content": "export const run = () => true;",
                    }
                ],
            },
            session={"user_id": 1},
        )

        with patch("blueprints.prompt_share.prompt_share_api._create_prompt_for_user") as mock_create:
            mock_create.return_value = 1
            response = asyncio.run(create_prompt(request))

        self.assertEqual(response.status_code, 201)
        resources = mock_create.call_args.args[-2]
        self.assertEqual(resources[0]["path"], "scripts/main.ts")
        self.assertEqual(resources[0]["language"], "typescript")


if __name__ == "__main__":
    unittest.main()
