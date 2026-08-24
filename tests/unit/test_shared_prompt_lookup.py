import unittest
from unittest.mock import AsyncMock, patch

from services.shared_prompt_lookup import (
    SharedPromptResult,
    build_shared_prompt_tool_payload,
    search_shared_prompts,
    search_shared_prompts_for_tool,
)


class _Summary:
    def __init__(self, prompt_id, title):
        self.prompt_id = prompt_id
        self.title = title
        self.category = "business"
        self.description = ""
        self.author = "ユーザー"
        self.content_format = "prompt"
        self.snippet = "検索スニペット"
        self.public_url = f"https://example.test/shared/prompt/{prompt_id}"


class _Page:
    def __init__(self, items):
        self.items = items


class _Detail:
    def __init__(self, content, skill_markdown="", description=""):
        self.content = content
        self.skill_markdown = skill_markdown
        self.description = description


class SharedPromptSearchTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_search_is_native_async_and_expands_top_hit(self):
        service = type("Service", (), {})()
        service.list_public_content = AsyncMock(return_value=_Page([_Summary(11, "返信")]))
        service.get_public_content = AsyncMock(return_value=_Detail("本文", description="用途"))
        with patch("services.shared_prompt_lookup._service", return_value=service):
            result = await search_shared_prompts("  メール 返信 ")
        self.assertEqual(result.prompts[0]["content"], "本文")
        self.assertEqual(result.prompts[0]["description"], "用途")
        service.list_public_content.assert_awaited_once()
        service.get_public_content.assert_awaited_once_with(11)

    async def test_skill_markdown_is_used_when_content_is_empty(self):
        service = type("Service", (), {})()
        service.list_public_content = AsyncMock(return_value=_Page([_Summary(12, "手順")]))
        service.get_public_content = AsyncMock(return_value=_Detail("", skill_markdown="# 手順"))
        with patch("services.shared_prompt_lookup._service", return_value=service):
            result = await search_shared_prompts("レビュー")
        self.assertEqual(result.prompts[0]["content"], "# 手順")

    async def test_body_failure_keeps_search_hit(self):
        service = type("Service", (), {})()
        service.list_public_content = AsyncMock(return_value=_Page([_Summary(13, "議事録")]))
        service.get_public_content = AsyncMock(side_effect=RuntimeError("db down"))
        with patch("services.shared_prompt_lookup._service", return_value=service):
            result = await search_shared_prompts("議事録")
        self.assertEqual(result.prompts[0]["title"], "議事録")
        self.assertNotIn("content", result.prompts[0])

    async def test_search_failure_is_distinguished_from_no_results(self):
        with patch("services.shared_prompt_lookup._service", side_effect=RuntimeError("boom")):
            result = await search_shared_prompts("メール")
        self.assertTrue(result.failed)
        payload = build_shared_prompt_tool_payload(result)
        self.assertEqual(payload["status"], "failed")

    async def test_tool_payload_entrypoint_is_async(self):
        with patch(
            "services.shared_prompt_lookup.search_shared_prompts",
            new=AsyncMock(return_value=SharedPromptResult(query="メール")),
        ) as search:
            payload = await search_shared_prompts_for_tool("メール")
        self.assertEqual(payload["status"], "no_results")
        search.assert_awaited_once_with("メール")

    async def test_blank_query_skips_service(self):
        with patch("services.shared_prompt_lookup._service") as factory:
            result = await search_shared_prompts("   ")
        factory.assert_not_called()
        self.assertFalse(result.has_hits)


if __name__ == "__main__":
    unittest.main()
