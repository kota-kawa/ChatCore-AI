import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mcp.server.fastmcp.exceptions import ToolError

from services.mcp_tools.common import consume_tool_limit, require_actor


class McpToolAuthorizationTestCase(unittest.TestCase):
    def test_require_actor_accepts_only_the_required_scope(self):
        token = SimpleNamespace(
            subject="42",
            client_id="client-a",
            scopes=["memos:read"],
        )
        with patch("services.mcp_tools.common.get_access_token", return_value=token):
            actor = require_actor("memos:read")

        self.assertEqual(actor.user_id, 42)
        self.assertEqual(actor.client_id, "client-a")

    def test_prompt_write_token_cannot_read_private_memos(self):
        token = SimpleNamespace(
            subject="42",
            client_id="legacy-client",
            scopes=["prompts:write"],
        )
        with patch("services.mcp_tools.common.get_access_token", return_value=token):
            with self.assertRaises(ToolError) as context:
                require_actor("memos:read")

        self.assertIn("memos:read", str(context.exception))

    def test_tool_limit_is_partitioned_by_user_and_client(self):
        actor = SimpleNamespace(user_id=42, client_id="client-a")
        with patch(
            "services.mcp_tools.common.run_blocking",
            return_value=(True, 1, 0),
        ) as mocked:
            asyncio.run(
                consume_tool_limit(
                    actor,
                    "memo_read",
                    limit=120,
                    window_seconds=60,
                )
            )

        self.assertEqual(mocked.call_args.args[2], "42:client-a")
        self.assertEqual(mocked.call_args.kwargs["limit"], 120)


if __name__ == "__main__":
    unittest.main()
