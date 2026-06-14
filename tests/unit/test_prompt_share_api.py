import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import get_prompt_detail


# 公開されているプロンプトの詳細情報を取得するAPIの挙動を検証するテストクラス。
# Test case class to verify the functionality and specifications of the prompt detail retrieval API.
class PromptShareApiTestCase(unittest.TestCase):
    # ID指定で正常に公開プロンプトの詳細情報がJSON形式で取得できることを検証します。
    # Verify that get prompt detail returns the requested public prompt payload successfully.
    def test_get_prompt_detail_returns_public_prompt(self):
        # モック用の公開プロンプトサンプルデータを定義
        # Define mock sample public prompt data
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

        # DB取得関数をモックしてAPI呼び出しを実行
        # Mock database lookup function and run prompt detail handler
        with patch(
            "blueprints.prompt_share.prompt_share_api._get_public_prompt_by_id",
            return_value=sample_prompt,
        ):
            response = asyncio.run(get_prompt_detail(12))

        # レスポンスステータスコードと取得データの正確性を検証
        # Verify response status code and correct payload properties
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["prompt"]["id"], 12)
        self.assertEqual(payload["prompt"]["title"], "共有タイトル")
        self.assertEqual(payload["prompt"]["skill_markdown"], "")

    # 指定されたプロンプトIDが存在しない場合に、APIが404エラーを返却することを検証します。
    # Verify that get prompt detail returns a 404 response for a non-existent prompt.
    def test_get_prompt_detail_returns_404_for_missing_prompt(self):
        # 存在しないプロンプトIDを指定した際のDB取得結果として None を返すようモック
        # Mock database lookup to return None for a missing prompt ID
        with patch(
            "blueprints.prompt_share.prompt_share_api._get_public_prompt_by_id",
            return_value=None,
        ):
            response = asyncio.run(get_prompt_detail(99))

        # 404ステータスコードと適切なエラーメッセージが返却されることを検証
        # Verify 404 status code and appropriate error payload message
        self.assertEqual(response.status_code, 404)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "プロンプトが見つかりません")


if __name__ == "__main__":
    unittest.main()
