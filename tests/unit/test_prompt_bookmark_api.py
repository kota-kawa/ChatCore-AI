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


# ブックマーク操作のAPIテスト用のHTTPリクエストを構築します。
# Build a mock HTTP request for testing prompt bookmark API endpoints.
def make_request(method, path, payload, session=None):
    return build_request(
        method=method,
        path=path,
        json_body=payload,
        session=session,
    )


# プロンプトのブックマーク追加・解除、マイタスク（保存）追加機能のAPIエンドポイントをテストするクラス。
# Test class to check API endpoints for prompt bookmarking, unbookmarking, and adding to my tasks.
class PromptBookmarkApiTestCase(unittest.TestCase):
    # プロンプトのブックマーク追加が、余分なコンテンツデータを要求せずprompt_idのみで処理できることを検証します。
    # Verify that adding a bookmark only requires prompt_id and succeeds without extra payload fields.
    def test_add_bookmark_uses_prompt_id_without_requiring_content(self):
        request = make_request(
            "POST",
            "/prompt_share/api/bookmark",
            {"prompt_id": 10},
            session={"user_id": 5},
        )

        # ブックマーク追加ヘルパーの戻り値をモック
        # Mock the helper response for adding a bookmark
        with patch(
            "blueprints.prompt_share.prompt_share_api._add_bookmark_for_user",
            return_value=({"message": "ブックマークが保存されました。"}, 201),
        ) as mock_add:
            response = asyncio.run(add_bookmark(request))

        self.assertEqual(response.status_code, 201)
        mock_add.assert_called_once_with(5, 10)

    # prompt_idが不足しているブックマーク追加要求が400エラーで拒否されることを検証します。
    # Verify that bookmark addition is rejected with a 400 error when prompt_id is missing.
    def test_add_bookmark_rejects_missing_prompt_id(self):
        request = make_request(
            "POST",
            "/prompt_share/api/bookmark",
            {},
            session={"user_id": 5},
        )

        # 不正なリクエストのため追加処理が呼ばれないことをモックで確認
        # Verify that the DB helper is not called for invalid request
        with patch("blueprints.prompt_share.prompt_share_api._add_bookmark_for_user") as mock_add:
            response = asyncio.run(add_bookmark(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "必要なフィールドが不足しています")
        mock_add.assert_not_called()

    # ブックマークの削除（解除）が、prompt_idに基づいて正常に処理されることを検証します。
    # Verify that removing a bookmark correctly processes using the provided prompt_id.
    def test_remove_bookmark_uses_prompt_id(self):
        request = make_request(
            "DELETE",
            "/prompt_share/api/bookmark",
            {"prompt_id": 10},
            session={"user_id": 5},
        )

        # ブックマーク削除処理をモック
        # Mock the bookmark removal helper
        with patch(
            "blueprints.prompt_share.prompt_share_api._remove_bookmark_for_user",
            return_value=1,
        ) as mock_remove:
            response = asyncio.run(remove_bookmark(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["bookmarked"])
        mock_remove.assert_called_once_with(5, 10)

    # 共有プロンプトを「マイタスク」として追加する処理が、専用のエンドポイントを通じて実行できることを検証します。
    # Verify that adding a prompt as a task goes through the dedicated task-creation endpoint.
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
