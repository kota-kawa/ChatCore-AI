import asyncio
import os
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from services import mcp_server
from services.request_models import SharedPromptCreateRequest


class McpServerTestCase(unittest.TestCase):
    def test_server_exposes_only_the_two_publish_tools(self):
        environment = {
            "MCP_PUBLIC_BASE_URL": "http://localhost:5004",
            "MCP_OAUTH_ENCRYPTION_KEYS": "5JZY8WHt_PU2CaUYi7ccVLq_rNfYQsg6dCXoyxa0Y0I=",
            "FASTAPI_ENV": "development",
        }
        with patch.dict(os.environ, environment, clear=False):
            server = mcp_server._create_mcp()
            tools = asyncio.run(server.list_tools())

        by_name = {tool.name: tool for tool in tools}
        self.assertEqual(set(by_name), {"publish_prompt", "publish_skill"})
        self.assertFalse(by_name["publish_prompt"].annotations.readOnlyHint)
        self.assertFalse(by_name["publish_prompt"].annotations.idempotentHint)
        for tool in by_name.values():
            self.assertEqual(
                tool.model_dump(by_alias=True)["securitySchemes"],
                [{"type": "oauth2", "scopes": ["prompts:write"]}],
            )

    def test_tools_publish_category_choices_and_structured_result_schema(self):
        environment = {
            "MCP_PUBLIC_BASE_URL": "http://localhost:5004",
            "MCP_OAUTH_ENCRYPTION_KEYS": "5JZY8WHt_PU2CaUYi7ccVLq_rNfYQsg6dCXoyxa0Y0I=",
            "FASTAPI_ENV": "development",
        }
        with patch.dict(os.environ, environment, clear=False):
            tools = asyncio.run(mcp_server._create_mcp().list_tools())

        for tool in tools:
            definition = tool.model_dump(by_alias=True)
            category = definition["inputSchema"]["properties"]["category"]
            self.assertIn("coding", category["enum"])
            self.assertIn("指定できる値", category["description"])
            output = definition["outputSchema"]
            self.assertEqual(set(output["required"]), {"prompt_id", "title", "content_format", "public_url"})

    def test_invalid_category_error_includes_allowed_values(self):
        with self.assertRaises(ValidationError) as context:
            SharedPromptCreateRequest(title="title", content="content", category="invalid")

        error = mcp_server._validation_tool_error(context.exception, "投稿")
        self.assertIn("カテゴリが不正", str(error))
        self.assertIn("coding", str(error))

    def test_authorization_metadata_advertises_cimd(self):
        with patch.dict(os.environ, {"MCP_PUBLIC_BASE_URL": "https://example.test"}, clear=False):
            metadata = mcp_server.get_oauth_authorization_metadata()

        self.assertTrue(metadata["client_id_metadata_document_supported"])
        self.assertEqual(metadata["scopes_supported"], ["prompts:write"])

    def test_issuer_matches_protected_resource_authorization_server(self):
        # RFC 8414 §3.3: the issuer must byte-match the authorization_servers value
        # the SDK serializes via AnyHttpUrl (trailing slash on a bare host).
        from pydantic import AnyHttpUrl

        with patch.dict(os.environ, {"MCP_PUBLIC_BASE_URL": "https://example.test"}, clear=False):
            metadata = mcp_server.get_oauth_authorization_metadata()

        self.assertEqual(metadata["issuer"], str(AnyHttpUrl("https://example.test")))
        # Endpoints must not gain a double slash from the normalized issuer.
        self.assertEqual(metadata["authorization_endpoint"], "https://example.test/authorize")
        self.assertEqual(metadata["token_endpoint"], "https://example.test/token")

    def test_mcp_endpoint_challenges_unauthenticated_clients(self):
        environment = {
            "MCP_PUBLIC_BASE_URL": "http://localhost:5004",
            "MCP_OAUTH_ENCRYPTION_KEYS": "5JZY8WHt_PU2CaUYi7ccVLq_rNfYQsg6dCXoyxa0Y0I=",
            "FASTAPI_ENV": "development",
        }
        previous_app = mcp_server._mcp_asgi_app
        previous_server = mcp_server._mcp
        try:
            with patch.dict(os.environ, environment, clear=False):
                mcp_server._mcp_asgi_app = None
                mcp_server._mcp = None

                async def request_endpoint():
                    transport = httpx.ASGITransport(app=mcp_server.get_mcp_asgi_app())
                    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:5004") as client:
                        return await client.post(
                            "/mcp",
                            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                        )

                response = asyncio.run(request_endpoint())
        finally:
            mcp_server._mcp_asgi_app = previous_app
            mcp_server._mcp = previous_server

        self.assertEqual(response.status_code, 401)
        self.assertIn("resource_metadata", response.headers["www-authenticate"])
