import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from blueprints.prompt_share.prompt_share_api import (
    _serialize_prompt_row,
    get_author_profile,
    get_prompt_detail,
    get_recommended_prompts,
)
from tests.helpers.request_helpers import build_request


class PromptShareApiTestCase(unittest.TestCase):
    def test_serializer_preserves_resource_and_legacy_script_fields(self):
        serialized = _serialize_prompt_row(
            {
                "id": 12,
                "title": "Skill",
                "content": "",
                "description": "Reusable skill description",
                "content_format": "skill",
                "media_type": "text",
                "attributes": {"skill_markdown": "# Skill"},
                "attachments": [],
                "resources": [{"path": "scripts/main.py", "role": "script", "size_bytes": 8}],
                "resource_python_script": "print(1)",
            }
        )
        self.assertEqual(serialized["resources"][0]["path"], "scripts/main.py")
        self.assertEqual(serialized["skill_python_script"], "print(1)")
        self.assertNotIn("resource_python_script", serialized)

    def test_get_prompt_detail_awaits_async_service_helper(self):
        sample_prompt = {
            "id": 12,
            "title": "共有タイトル",
            "category": "business",
            "content": "内容",
            "description": "説明",
            "author": "tester",
            "input_examples": "input",
            "output_examples": "output",
            "content_format": "prompt",
            "media_type": "text",
            "attributes": {},
            "attachments": [],
            "created_at": datetime(2024, 1, 2, 3, 4, 5),
        }
        with patch(
            "blueprints.prompt_share.prompt_share_api._get_public_prompt_by_id",
            new=AsyncMock(return_value=sample_prompt),
        ):
            response = asyncio.run(get_prompt_detail(12))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode())["prompt"]["id"], 12)

    def test_get_prompt_detail_returns_404_for_missing_prompt(self):
        with patch(
            "blueprints.prompt_share.prompt_share_api._get_public_prompt_by_id",
            new=AsyncMock(return_value=None),
        ):
            response = asyncio.run(get_prompt_detail(99))
        self.assertEqual(response.status_code, 404)

    def test_recommendations_await_async_helper(self):
        sample_prompts = [{"id": 21, "title": "おすすめプロンプト", "content": "内容"}]
        with patch(
            "blueprints.prompt_share.prompt_share_api._get_recommended_prompts",
            new=AsyncMock(return_value=sample_prompts),
        ) as recommended:
            request = build_request(
                method="GET",
                path="/prompt_share/api/prompts/recommended",
                headers=[(b"accept-language", b"en")],
            )
            response = asyncio.run(get_recommended_prompts(request, exclude_id=12))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode())["prompts"], sample_prompts)
        recommended.assert_awaited_once_with(12, 3, "en")

    def test_author_profile_awaits_async_helper(self):
        profile = {"id": 7, "username": "tester", "prompt_count": 3}
        with patch(
            "blueprints.prompt_share.prompt_share_api._get_public_author_profile",
            new=AsyncMock(return_value=profile),
        ):
            response = asyncio.run(get_author_profile(7))
        self.assertEqual(json.loads(response.body.decode())["user"], profile)


if __name__ == "__main__":
    unittest.main()
