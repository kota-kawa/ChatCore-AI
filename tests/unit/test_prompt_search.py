import asyncio
import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_search import _search_public_prompts


class StubSharedContentService:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def search_public_prompts(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class PromptSearchTestCase(unittest.TestCase):
    @staticmethod
    def _row(**overrides):
        row = {
            "id": 11,
            "title": "sample",
            "category": "business",
            "content": "body",
            "description": "description",
            "author": "tester",
            "input_examples": "",
            "output_examples": "",
            "content_format": "prompt",
            "media_type": "text",
            "attributes": {},
            "attachments": [],
            "resources": [],
            "resource_python_script": "",
            "view_count": 9,
            "created_at": "2024-01-01T00:00:00",
            "liked": True,
            "used_in_chat": True,
            "added_to_skills": True,
            "comment_count": 2,
        }
        row.update(overrides)
        return row

    def test_search_maps_service_rows_and_pagination(self):
        service = StubSharedContentService(
            {"rows": [self._row()], "total": 55, "has_next": True}
        )

        with patch(
            "blueprints.prompt_share.prompt_search.SharedContentService",
            return_value=service,
        ):
            payload = asyncio.run(_search_public_prompts("sample", 2, 20, 9))

        prompt = payload["prompts"][0]
        self.assertEqual(prompt["id"], 11)
        self.assertTrue(prompt["liked"])
        self.assertTrue(prompt["used_in_chat"])
        self.assertTrue(prompt["added_to_skills"])
        self.assertEqual(prompt["view_count"], 9)
        self.assertEqual(prompt["comment_count"], 2)
        self.assertEqual(payload["pagination"]["total"], 55)
        self.assertEqual(payload["pagination"]["total_pages"], 3)
        self.assertTrue(payload["pagination"]["has_next"])
        self.assertTrue(payload["pagination"]["has_prev"])
        self.assertEqual(service.calls[0]["matching_category_keys"], [])

    def test_search_maps_legacy_prompt_type_to_two_axes(self):
        service = StubSharedContentService({"rows": [], "total": 0, "has_next": False})
        with patch(
            "blueprints.prompt_share.prompt_search.SharedContentService",
            return_value=service,
        ):
            asyncio.run(_search_public_prompts("sample", 1, 10, 9, "image"))

        self.assertEqual(service.calls[0]["content_format"], "prompt")
        self.assertEqual(service.calls[0]["media_type"], "image")

    def test_search_passes_explicit_two_axis_filters(self):
        service = StubSharedContentService({"rows": [], "total": 0, "has_next": False})
        with patch(
            "blueprints.prompt_share.prompt_search.SharedContentService",
            return_value=service,
        ):
            asyncio.run(
                _search_public_prompts(
                    "sample",
                    1,
                    10,
                    9,
                    content_format="skill",
                    media_type="text",
                )
            )

        self.assertEqual(service.calls[0]["content_format"], "skill")
        self.assertEqual(service.calls[0]["media_type"], "text")

    def test_search_resolves_category_label_to_keys(self):
        service = StubSharedContentService({"rows": [], "total": 0, "has_next": False})
        with patch(
            "blueprints.prompt_share.prompt_search.SharedContentService",
            return_value=service,
        ):
            asyncio.run(_search_public_prompts("プログラミング", 1, 10, 9))

        self.assertEqual(service.calls[0]["matching_category_keys"], ["coding"])

    def test_blank_search_avoids_service_and_returns_empty_payload(self):
        with patch("blueprints.prompt_share.prompt_search.SharedContentService") as service_factory:
            payload = asyncio.run(_search_public_prompts("", 1, 20))

        self.assertEqual(payload["prompts"], [])
        self.assertEqual(payload["pagination"]["total"], 0)
        self.assertFalse(payload["pagination"]["has_next"])
        service_factory.assert_not_called()

    def test_later_pages_use_service_has_next_without_total(self):
        service = StubSharedContentService(
            {
                "rows": [self._row(id=index, title=f"sample-{index}") for index in range(11)],
                "total": None,
                "has_next": True,
            }
        )
        with patch(
            "blueprints.prompt_share.prompt_search.SharedContentService",
            return_value=service,
        ):
            payload = asyncio.run(_search_public_prompts("sample", 2, 10, 9, include_total=False))

        self.assertIsNone(payload["pagination"]["total"])
        self.assertTrue(payload["pagination"]["has_next"])
        self.assertEqual(len(payload["prompts"]), 11)
        self.assertFalse(service.calls[0]["include_total"])


if __name__ == "__main__":
    unittest.main()
