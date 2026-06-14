import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from blueprints.prompt_share.prompt_manage_api import (
    _serialize_prompt_list_entry,
    get_prompt_list,
)
from tests.helpers.request_helpers import build_request


# 保存済みプロンプトリストAPIのエンドポイントの挙動や、プロンプトリスト要素のシリアライズ処理をテストするクラス。
# Test class to check the behavior of the saved prompt list API endpoint and the serialization of prompt list entries.
class PromptManageApiTestCase(unittest.TestCase):
    # 保存済みプロンプトリスト取得APIが、正規化されたエントリ形式のJSONレスポンスを返すことを検証します。
    # Verify that the saved prompt list API returns a JSON response containing normalized entry shapes.
    def test_prompt_list_returns_normalized_entry_shape(self):
        # ユーザーIDを含むセッションで、プロンプトリスト取得用リクエストオブジェクトを構築
        # Build the request object for fetching the prompt list with a user ID in the session
        request = build_request(
            method="GET",
            path="/prompt_manage/api/prompt_list",
            session={"user_id": 99},
        )
        
        # テスト用のサンプルデータエントリを設定
        # Configure sample entry data for testing
        sample_entries = [
            {
                "id": 12,
                "prompt_id": 34,
                "created_at": "2024-01-02T03:04:05",
                "prompt": {
                    "id": 34,
                    "title": "title",
                    "category": "cat",
                    "content": "content",
                    "author": "author",
                    "input_examples": "in",
                    "output_examples": "out",
                    "created_at": "2024-01-01T10:00:00",
                },
            }
        ]

        # エントリ一覧取得ヘルパー関数をモックしてAPI呼び出しを実行
        # Mock the helper function fetching prompt list entries and run the API handler
        with patch(
            "blueprints.prompt_share.prompt_manage_api._fetch_prompt_list",
            return_value=sample_entries,
        ):
            response = asyncio.run(get_prompt_list(request))

        # レスポンスステータス、および返却されたJSON内のエントリ情報が期待通りであることを検証
        # Verify response status and that returned JSON contains the expected entry details
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        entry = payload["prompts"][0]
        self.assertEqual(entry["id"], 12)
        self.assertEqual(entry["prompt_id"], 34)
        self.assertEqual(entry["created_at"], "2024-01-02T03:04:05")
        self.assertEqual(entry["prompt"]["id"], 34)
        self.assertEqual(entry["prompt"]["title"], "title")

    # プロンプトリスト項目のシリアライズ処理が、保存された日時(saved_at)とプロンプトが作成された日時(prompt_created_at)を混同せず正しくシリアライズすることを検証します。
    # Verify that the prompt list entry serialization correctly keeps saved_at and prompt_created_at timestamps separate.
    def test_serialize_prompt_list_entry_keeps_entry_and_prompt_timestamps_separate(self):
        # 異なる日時を設定したプロンプトリストエントリをシリアライズ関数に投入
        # Pass a prompt list entry with distinct timestamps into the serialization function
        serialized = _serialize_prompt_list_entry(
            {
                "entry_id": 12,
                "prompt_id": 34,
                "title": "title",
                "category": "cat",
                "content": "content",
                "author": "author",
                "input_examples": "in",
                "output_examples": "out",
                "saved_at": datetime(2024, 1, 2, 3, 4, 5),
                "prompt_created_at": datetime(2024, 1, 1, 10, 11, 12),
            }
        )

        # 保存日(created_at)とプロンプト作成日(prompt.created_at)が独立して正しく変換されていることを検証
        # Verify that saved_at (serialized as created_at) and prompt_created_at are converted correctly and independently
        self.assertEqual(serialized["id"], 12)
        self.assertEqual(serialized["prompt_id"], 34)
        self.assertEqual(serialized["created_at"], "2024-01-02T03:04:05")
        self.assertEqual(serialized["prompt"]["created_at"], "2024-01-01T10:11:12")


if __name__ == "__main__":
    unittest.main()
