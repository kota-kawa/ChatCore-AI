import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services import mcp_server
from services.response_models import ContextDigestResponse, ContextFactResponse


MCP_ENVIRONMENT = {
    "MCP_PUBLIC_BASE_URL": "http://localhost:5004",
    "MCP_OAUTH_ENCRYPTION_KEYS": "5JZY8WHt_PU2CaUYi7ccVLq_rNfYQsg6dCXoyxa0Y0I=",
    "FASTAPI_ENV": "development",
}


class McpContextVaultToolTestCase(unittest.TestCase):
    def _server(self):
        with patch.dict(os.environ, MCP_ENVIRONMENT, clear=False):
            return mcp_server._create_mcp()

    def test_context_tool_annotations_describe_read_and_mutation_effects(self):
        tools = asyncio.run(self._server().list_tools())
        by_name = {tool.name: tool for tool in tools}

        for name in ("get_personal_context", "search_context"):
            annotations = by_name[name].annotations
            self.assertTrue(annotations.readOnlyHint)
            self.assertTrue(annotations.idempotentHint)
            self.assertFalse(annotations.destructiveHint)
            self.assertFalse(annotations.openWorldHint)

        create_annotations = by_name["save_context_fact"].annotations
        self.assertFalse(create_annotations.readOnlyHint)
        self.assertFalse(create_annotations.idempotentHint)
        self.assertFalse(create_annotations.destructiveHint)
        self.assertFalse(create_annotations.openWorldHint)

        for name in ("update_context_fact", "deprecate_context_fact"):
            annotations = by_name[name].annotations
            self.assertFalse(annotations.readOnlyHint)
            self.assertFalse(annotations.idempotentHint)
            self.assertTrue(annotations.destructiveHint)
            self.assertFalse(annotations.openWorldHint)

    def test_digest_uses_context_read_rate_bucket(self):
        server = self._server()
        actor = SimpleNamespace(user_id=7, client_id="client-a")
        rate_limit = AsyncMock()
        with (
            patch("services.mcp_tools.context_vault.require_actor", return_value=actor),
            patch("services.mcp_tools.context_vault.consume_tool_limit", new=rate_limit),
            patch(
                "services.mcp_tools.context_vault.run_blocking",
                new=AsyncMock(return_value=ContextDigestResponse()),
            ),
        ):
            asyncio.run(server.call_tool("get_personal_context", {}))

        rate_limit.assert_awaited_once_with(
            actor,
            "context_read",
            limit=120,
            window_seconds=60,
        )

    def test_semantic_search_uses_read_and_semantic_rate_buckets(self):
        server = self._server()
        actor = SimpleNamespace(user_id=7, client_id="client-a")
        rate_limit = AsyncMock()
        with (
            patch("services.mcp_tools.context_vault.require_actor", return_value=actor),
            patch("services.mcp_tools.context_vault.consume_tool_limit", new=rate_limit),
            patch(
                "services.mcp_tools.context_vault.run_blocking",
                new=AsyncMock(return_value={"total": 0, "facts": []}),
            ),
        ):
            asyncio.run(
                server.call_tool(
                    "search_context",
                    {"query": "editor", "mode": "semantic"},
                )
            )

        self.assertEqual(
            [call.args[1] for call in rate_limit.await_args_list],
            ["context_read", "context_semantic_search"],
        )
        self.assertEqual(rate_limit.await_args_list[0].kwargs, {"limit": 120, "window_seconds": 60})
        self.assertEqual(rate_limit.await_args_list[1].kwargs, {"limit": 30, "window_seconds": 3600})

    def test_context_mutations_use_write_limit_and_emit_success_audit(self):
        actor = SimpleNamespace(user_id=7, client_id="client-a")
        cases = (
            (
                "save_context_fact",
                {"fact_type": "preference", "title": "Editor", "content": "Use Vim"},
            ),
            (
                "update_context_fact",
                {"fact_id": 11, "expected_revision": 3, "title": "Updated editor"},
            ),
            (
                "deprecate_context_fact",
                {"fact_id": 11, "expected_revision": 3},
            ),
        )

        for tool_name, arguments in cases:
            with self.subTest(tool=tool_name):
                server = self._server()
                fact = ContextFactResponse(
                    id=11,
                    fact_type="preference",
                    title="Editor",
                    content="Use Vim",
                    status="deprecated" if tool_name == "deprecate_context_fact" else "active",
                    revision=4,
                )
                rate_limit = AsyncMock()
                with (
                    patch("services.mcp_tools.context_vault.require_actor", return_value=actor),
                    patch("services.mcp_tools.context_vault.consume_tool_limit", new=rate_limit),
                    patch(
                        "services.mcp_tools.context_vault.run_blocking",
                        new=AsyncMock(return_value=fact),
                    ),
                    patch("services.mcp_tools.context_vault.audit_tool_success") as audit,
                ):
                    asyncio.run(server.call_tool(tool_name, arguments))

                rate_limit.assert_awaited_once_with(
                    actor,
                    "context_write",
                    limit=60,
                    window_seconds=3600,
                )
                audit.assert_called_once_with(actor, tool_name, 11)


if __name__ == "__main__":
    unittest.main()
