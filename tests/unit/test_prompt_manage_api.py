import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from blueprints.prompt_share.prompt_manage_api import (
    _serialize_liked_prompt,
    get_liked_prompts,
)
from tests.helpers.request_helpers import build_request


# いいねしたプロンプトAPIのエンドポイントの挙動や、いいね要素のシリアライズ処理をテストするクラス。
# Test class to check the behavior of the liked prompts API endpoint and serialization.
class PromptManageApiTestCase(unittest.TestCase):
    # いいねしたプロンプト取得APIが、正規化されたJSONレスポンスを返すことを検証します。
    # Verify that the liked prompts API returns a JSON response containing normalized prompt shapes.
    def test_liked_prompts_returns_normalized_entry_shape(self):
        request = build_request(
            method="GET",
            path="/prompt_manage/api/liked_prompts",
            session={"user_id": 99},
        )

        sample_entries = [
            {
                "id": 12,
                "like_id": 12,
                "prompt_id": 34,
                "title": "title",
                "category": "cat",
                "content": "content",
                "author": "author",
                "input_examples": "in",
                "output_examples": "out",
                "created_at": "2024-01-01T10:00:00",
                "prompt_created_at": "2024-01-01T10:00:00",
                "liked_at": "2024-01-02T03:04:05",
                "liked": True,
            }
        ]

        with patch(
            "blueprints.prompt_share.prompt_manage_api._fetch_liked_prompts",
            return_value=sample_entries,
        ):
            response = asyncio.run(get_liked_prompts(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        entry = payload["prompts"][0]
        self.assertEqual(entry["id"], 12)
        self.assertEqual(entry["like_id"], 12)
        self.assertEqual(entry["prompt_id"], 34)
        self.assertEqual(entry["title"], "title")
        self.assertEqual(entry["liked_at"], "2024-01-02T03:04:05")
        self.assertTrue(entry["liked"])

    # いいね日時とプロンプト作成日時を混同せず正しくシリアライズすることを検証します。
    # Verify that liked_at and prompt_created_at timestamps remain distinct in serialization.
    def test_serialize_liked_prompt_keeps_like_and_prompt_timestamps_separate(self):
        serialized = _serialize_liked_prompt(
            {
                "like_id": 12,
                "prompt_id": 34,
                "title": "title",
                "category": "cat",
                "content": "content",
                "author": "author",
                "input_examples": "in",
                "output_examples": "out",
                "liked_at": datetime(2024, 1, 2, 3, 4, 5),
                "prompt_created_at": datetime(2024, 1, 1, 10, 11, 12),
            }
        )

        self.assertEqual(serialized["id"], 12)
        self.assertEqual(serialized["like_id"], 12)
        self.assertEqual(serialized["prompt_id"], 34)
        self.assertEqual(serialized["liked_at"], "2024-01-02T03:04:05")
        self.assertEqual(serialized["prompt_created_at"], "2024-01-01T10:11:12")
        self.assertEqual(serialized["created_at"], "2024-01-01T10:11:12")


if __name__ == "__main__":
    unittest.main()
