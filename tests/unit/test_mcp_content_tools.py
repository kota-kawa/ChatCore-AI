import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services import mcp_server
from services.mcp_memo_service import McpMemoDetail
from services.request_models import SharedPromptCreateRequest
from services.shared_content_service import (
    PublicSharedContentDetail,
    PublicSharedContentPage,
    PublicSkillResourceDetail,
    PublicSkillResourceMetadata,
)


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
                "services.mcp_tools.shared_content.SharedContentService.list_public_content",
                new=AsyncMock(return_value=page),
            ) as list_content,
        ):
            result = asyncio.run(
                server.call_tool(
                    "search_shared_content",
                    {"query": "skill", "limit": 20, "content_format": "skill"},
                )
            )

        structured = result[1]
        self.assertEqual(structured["has_next"], False)
        self.assertEqual(list_content.call_args.kwargs["query"], "skill")
        self.assertEqual(list_content.call_args.kwargs["content_format"], "skill")

    def test_publish_skill_uses_resources_as_canonical_input(self):
        server = self._server()
        publish_result = mcp_server.McpPublishResult(
            prompt_id=91,
            title="TypeScript Skill",
            content_format="skill",
            public_url="https://example.test/shared/prompt/91",
        )
        with (
            patch(
                "services.mcp_server.require_actor",
                return_value=SimpleNamespace(user_id=7, client_id="client-a"),
            ),
            patch(
                "services.mcp_server._publish",
                new=AsyncMock(return_value=publish_result),
            ) as publish,
            patch("services.mcp_server.audit_tool_success"),
        ):
            result = asyncio.run(
                server.call_tool(
                    "publish_skill",
                    {
                        "title": "TypeScript Skill",
                        "skill_markdown": "# TypeScript Skill",
                        "resources": [
                            {
                                "path": "scripts/run.ts",
                                "role": "script",
                                "language": "typescript",
                                "content": "export const run = () => true;",
                            }
                        ],
                    },
                )
            )

        structured = result[1]
        self.assertEqual(structured["prompt_id"], 91)
        payload = publish.call_args.args[1]
        self.assertEqual(payload.resources[0].path, "scripts/run.ts")
        self.assertEqual(payload.resources[0].language, "typescript")
        self.assertEqual(payload.attributes, {"skill_markdown": "# TypeScript Skill"})

    def test_publish_prompt_forwards_a_reference_image_and_selects_image_media(self):
        server = self._server()
        publish_result = mcp_server.McpPublishResult(
            prompt_id=92,
            title="Image prompt",
            content_format="prompt",
            media_type="image",
            public_url="https://example.test/shared/prompt/92",
        )
        with (
            patch(
                "services.mcp_server.require_actor",
                return_value=SimpleNamespace(user_id=7, client_id="client-a"),
            ),
            patch(
                "services.mcp_server._publish",
                new=AsyncMock(return_value=publish_result),
            ) as publish,
            patch("services.mcp_server.audit_tool_success"),
        ):
            result = asyncio.run(
                server.call_tool(
                    "publish_prompt",
                    {
                        "title": "Image prompt",
                        "content": "Generate a watercolor landscape.",
                        "image_base64": "cG5nLWJ5dGVz",
                        "image_filename": "example.png",
                        "image_mime_type": "image/png",
                    },
                )
            )

        structured = result[1]
        self.assertEqual(structured["prompt_id"], 92)
        payload = publish.call_args.args[1]
        self.assertEqual(payload.media_type, "image")
        self.assertEqual(publish.call_args.kwargs["image_base64"], "cG5nLWJ5dGVz")
        self.assertEqual(publish.call_args.kwargs["image_filename"], "example.png")
        self.assertEqual(publish.call_args.kwargs["image_mime_type"], "image/png")

    def test_publish_removes_saved_image_when_database_write_fails(self):
        payload = SharedPromptCreateRequest(
            title="Image prompt",
            content="Generate a watercolor landscape.",
            media_type="image",
        )
        attachment = {
            "url": "/prompt_share/api/media/user_7_image.webp",
            "thumbnail_url": "/prompt_share/api/media/user_7_image_card.webp",
        }
        with (
            patch("services.mcp_server._consume_publish_limit", new=AsyncMock()),
            patch("services.mcp_server.save_mcp_prompt_image", return_value=attachment),
            patch(
                "services.mcp_server.create_shared_prompt",
                new=AsyncMock(side_effect=RuntimeError("database unavailable")),
            ),
            patch("services.mcp_server.delete_prompt_attachment") as delete_attachment,
        ):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                asyncio.run(
                    mcp_server._publish(
                        7,
                        payload,
                        image_base64="encoded-image",
                        image_filename="image.png",
                        image_mime_type="image/png",
                    )
                )

        delete_attachment.assert_called_once_with(attachment)

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
                "services.mcp_tools.memos.get_memo",
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
                "services.mcp_tools.shared_content.SharedContentService.get_public_content",
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

    def test_list_skill_resources_returns_metadata_without_content(self):
        server = self._server()
        resources = [
            PublicSkillResourceMetadata(
                path="scripts/run.ts",
                role="script",
                language="typescript",
                media_type="text/typescript",
                size_bytes=42,
                sha256="abc",
            )
        ]
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
                "services.mcp_tools.shared_content.SharedContentService.list_public_skill_resources",
                new=AsyncMock(return_value=resources),
            ),
        ):
            result = asyncio.run(
                server.call_tool("list_skill_resources", {"prompt_id": 8})
            )

        structured = result[1]
        self.assertEqual(structured["prompt_id"], 8)
        self.assertEqual(structured["resources"][0]["path"], "scripts/run.ts")
        self.assertNotIn("content", structured["resources"][0])

    def test_get_skill_resource_returns_only_requested_content_slice(self):
        server = self._server()
        resource = PublicSkillResourceDetail(
            path="references/api.md",
            role="reference",
            language="markdown",
            media_type="text/markdown",
            size_bytes=10,
            sha256="def",
            content="0123456789",
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
                "services.mcp_tools.shared_content.SharedContentService.get_public_skill_resource",
                new=AsyncMock(return_value=resource),
            ) as get_resource,
        ):
            result = asyncio.run(
                server.call_tool(
                    "get_skill_resource",
                    {
                        "prompt_id": 8,
                        "path": "references/api.md",
                        "content_offset": 3,
                        "content_limit": 4,
                    },
                )
            )

        structured = result[1]
        self.assertEqual(structured["text"], "3456")
        self.assertEqual(structured["total_characters"], 10)
        self.assertEqual(structured["next_offset"], 7)
        self.assertEqual(
            get_resource.call_args.args[1:],
            ("references/api.md",),
        )


if __name__ == "__main__":
    unittest.main()
