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


class PromptManageApiTestCase(unittest.TestCase):
    def test_prompt_list_returns_normalized_entry_shape(self):
        request = build_request(
            method="GET",
            path="/prompt_manage/api/prompt_list",
            session={"user_id": 99},
        )
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

        with patch(
            "blueprints.prompt_share.prompt_manage_api._fetch_prompt_list",
            return_value=sample_entries,
        ):
            response = asyncio.run(get_prompt_list(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        entry = payload["prompts"][0]
        self.assertEqual(entry["id"], 12)
        self.assertEqual(entry["prompt_id"], 34)
        self.assertEqual(entry["created_at"], "2024-01-02T03:04:05")
        self.assertEqual(entry["prompt"]["id"], 34)
        self.assertEqual(entry["prompt"]["title"], "title")

    def test_serialize_prompt_list_entry_keeps_entry_and_prompt_timestamps_separate(self):
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

        self.assertEqual(serialized["id"], 12)
        self.assertEqual(serialized["prompt_id"], 34)
        self.assertEqual(serialized["created_at"], "2024-01-02T03:04:05")
        self.assertEqual(serialized["prompt"]["created_at"], "2024-01-01T10:11:12")


if __name__ == "__main__":
    unittest.main()
