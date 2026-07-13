import os
import unittest
from unittest.mock import patch

from services.mcp_config import get_mcp_public_base_url, is_mcp_enabled


class McpConfigTestCase(unittest.TestCase):
    def test_mcp_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_mcp_enabled())

    def test_mcp_is_enabled_for_true_values(self):
        with patch.dict(os.environ, {"MCP_ENABLED": "true"}, clear=True):
            self.assertTrue(is_mcp_enabled())

    def test_public_base_url_strips_trailing_slash(self):
        with patch.dict(os.environ, {"MCP_PUBLIC_BASE_URL": "https://example.test/"}, clear=True):
            self.assertEqual(get_mcp_public_base_url(), "https://example.test")
