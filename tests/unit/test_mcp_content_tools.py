import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services import mcp_server
from services.mcp_memo_service import McpMemoDetail
from services.shared_content_service import PublicSharedContentDetail, PublicSharedContentPage


MCP_ENVIRONMENT = {
    "MCP_PUBLIC_BASE_URL": "http://localhost:5004",
    "MCP_OAUTH_ENCRYPTION_KEYS": "5JZY8WHt_PU2CaUYi7ccVLq_rNfYQsg6dCXoyxa0Y0I=",
    "FASTAPI_ENV": "development",
}


class McpContentToolTestCase(unittest.TestCase):
    def _server(self):
        with patch.dict(os.environ, MCP_ENVIRONMENT, clear=False):
            return mcp_server._create_mcp()

    def test_search_shared_content_delegates_with_bounded_arguments(self):
        server = self._server()
        page = PublicSharedContentPage(items=[], limit=20, has_next=False)
        with (
            patch(
                "services.mcp_tools.shared_content.require_actor",
                return_value=SimpleNamespace(user_id=7, client_id="client-a"),
            ),
            patch(
                "services.mcp_tools.shared_content.consume_tool_limit",
                new=AsyncMock(),
            ),
            patch(
                "services.mcp_tools.shared_content.run_blocking",
                new=AsyncMock(return_value=page),
            ) as run_blocking,
        ):
            result = asyncio.run(
                server.call_tool(
                    "search_shared_content",
                    {"query": "skill", "limit": 20, "content_format": "skill"},
                )
            )

        structured = result[1]
        self.assertEqual(structured["has_next"], False)
        self.assertEqual(run_blocking.call_args.kwargs["query"], "skill")
        self.assertEqual(run_blocking.call_args.kwargs["content_format"], "skill")

    def test_get_memo_returns_only_the_requested_content_slice(self):
        server = self._server()
        memo = McpMemoDetail(
            id=3,
            title="Private memo",
            content="0123456789",
            created_at=datetime(2026, 7, 16, 12, 0, 0).isoformat(),
            updated_at=datetime(2026, 7, 16, 13, 0, 0).isoformat(),
            revision=4,
            is_shared=False,
        )
        with (
            patch(
                "services.mcp_tools.memos.require_actor",
                return_value=SimpleNamespace(user_id=7, client_id="client-a"),
            ),
            patch(
                "services.mcp_tools.memos.consume_tool_limit",
                new=AsyncMock(),
            ),
            patch(
                "services.mcp_tools.memos.run_blocking",
                new=AsyncMock(return_value=memo),
            ),
        ):
            result = asyncio.run(
                server.call_tool(
                    "get_memo",
                    {"memo_id": 3, "content_offset": 3, "content_limit": 4},
                )
            )

        structured = result[1]
        self.assertEqual(structured["content"], "3456")
        self.assertEqual(structured["total_characters"], 10)
        self.assertEqual(structured["next_offset"], 7)
        self.assertNotIn("share_token", structured)

    def test_get_shared_content_returns_one_bounded_section(self):
        server = self._server()
        detail = PublicSharedContentDetail(
            prompt_id=8,
            title="Skill",
            category="coding",
            content="",
            author="tester",
            content_format="skill",
            media_type="text",
            skill_markdown="abcdefghij",
            skill_python_script="print('x')",
            created_at=datetime(2026, 7, 16, 12, 0, 0),
            public_url="https://example.test/shared/prompt/8",
        )
        with (
            patch(
                "services.mcp_tools.shared_content.require_actor",
                return_value=SimpleNamespace(user_id=7, client_id="client-a"),
            ),
            patch(
                "services.mcp_tools.shared_content.consume_tool_limit",
                new=AsyncMock(),
            ),
            patch(
                "services.mcp_tools.shared_content.run_blocking",
                new=AsyncMock(return_value=detail),
            ),
        ):
            result = asyncio.run(
                server.call_tool(
                    "get_shared_content",
                    {"prompt_id": 8, "section": "auto", "content_offset": 2, "content_limit": 4},
                )
            )

        structured = result[1]
        self.assertEqual(structured["section"], "skill_markdown")
        self.assertEqual(structured["text"], "cdef")
        self.assertEqual(structured["next_offset"], 6)
        self.assertNotIn("attributes", structured)


if __name__ == "__main__":
    unittest.main()
