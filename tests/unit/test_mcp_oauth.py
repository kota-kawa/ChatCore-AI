import unittest
from unittest.mock import patch

from mcp.shared.auth import OAuthClientInformationFull

from services import mcp_oauth


class McpOAuthTestCase(unittest.TestCase):
    def test_consent_details_exposes_client_and_redirect_hosts(self):
        client = OAuthClientInformationFull(
            client_id="https://client.example.test/metadata.json",
            redirect_uris=["https://client.example.test/callback"],
            client_name="Example AI",
            token_endpoint_auth_method="none",
        )
        payload = {
            "client": mcp_oauth._serialize_client(client),
            "params": {
                "state": "state",
                "scopes": ["prompts:write"],
                "code_challenge": "challenge",
                "redirect_uri": "https://client.example.test/callback",
                "resource": "https://chat.example.test/mcp",
            },
        }
        with patch("services.mcp_oauth.get_session_secret_key", return_value="test-secret"):
            token = mcp_oauth._consent_serializer().dumps(payload)
            details = mcp_oauth.consent_details(token)

        self.assertEqual(details["client_name"], "Example AI")
        self.assertEqual(details["client_host"], "client.example.test")
        self.assertFalse(details["localhost_warning"])

    def test_redirect_validation_rejects_non_loopback_http(self):
        client = OAuthClientInformationFull(
            client_id="client",
            redirect_uris=["http://example.test/callback"],
            token_endpoint_auth_method="none",
        )
        with self.assertRaises(mcp_oauth.RegistrationError):
            mcp_oauth._validate_redirect_uris(client)
