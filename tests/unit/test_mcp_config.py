import os
import unittest
from unittest.mock import patch

from services.mcp_config import (
    get_mcp_allowed_hosts,
    get_mcp_public_base_url,
    is_mcp_enabled,
)


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

    def test_public_base_url_rejects_components_that_break_discovery_urls(self):
        invalid_urls = (
            "https://example.test?tenant=x",
            "https://example.test/#fragment",
            "https://user:pass@example.test",
            "https://example.test/mcp",
        )
        for url in invalid_urls:
            with self.subTest(url=url), patch.dict(os.environ, {"MCP_PUBLIC_BASE_URL": url}, clear=True):
                with self.assertRaises(ValueError):
                    get_mcp_public_base_url()

    def test_allowed_hosts_default_includes_www_sibling(self):
        with patch.dict(os.environ, {"MCP_PUBLIC_BASE_URL": "https://example.test"}, clear=True):
            self.assertEqual(get_mcp_allowed_hosts(), ["example.test", "www.example.test"])

    def test_allowed_hosts_default_includes_apex_sibling_for_www_base(self):
        with patch.dict(os.environ, {"MCP_PUBLIC_BASE_URL": "https://www.example.test"}, clear=True):
            self.assertEqual(get_mcp_allowed_hosts(), ["www.example.test", "example.test"])

    def test_allowed_hosts_can_be_overridden(self):
        with patch.dict(
            os.environ,
            {"MCP_PUBLIC_BASE_URL": "https://example.test", "MCP_ALLOWED_HOSTS": "a.test, b.test"},
            clear=True,
        ):
            self.assertEqual(get_mcp_allowed_hosts(), ["a.test", "b.test"])
