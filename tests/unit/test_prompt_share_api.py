import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import get_prompt_detail


# 日本語: Prompt Share Apiの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Prompt Share Api.
class PromptShareApiTestCase(unittest.TestCase):
    # 日本語: getプロンプトdetail返却するpublicプロンプトことを検証します。
    # English: Verify that get prompt detail returns public prompt.
    def test_get_prompt_detail_returns_public_prompt(self):
        sample_prompt = {
            "id": 12,
            "title": "共有タイトル",
            "category": "仕事",
            "content": "内容",
            "author": "tester",
            "input_examples": "input",
            "output_examples": "output",
            "ai_model": "gemini-2.5-flash",
            "prompt_type": "text",
            "reference_image_url": None,
            "skill_markdown": "",
            "skill_python_script": "",
            "created_at": datetime(2024, 1, 2, 3, 4, 5).isoformat(),
        }

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "blueprints.prompt_share.prompt_share_api._get_public_prompt_by_id",
            return_value=sample_prompt,
        ):
            response = asyncio.run(get_prompt_detail(12))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["prompt"]["id"], 12)
        self.assertEqual(payload["prompt"]["title"], "共有タイトル")
        self.assertEqual(payload["prompt"]["skill_markdown"], "")

    # 日本語: missingプロンプトに対して、getプロンプトdetail返却する404ことを検証します。
    # English: Verify that get prompt detail returns 404 for missing prompt.
    def test_get_prompt_detail_returns_404_for_missing_prompt(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "blueprints.prompt_share.prompt_share_api._get_public_prompt_by_id",
            return_value=None,
        ):
            response = asyncio.run(get_prompt_detail(99))

        self.assertEqual(response.status_code, 404)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "プロンプトが見つかりません")


if __name__ == "__main__":
    unittest.main()
