import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.mcp_oauth import patch_client, patch_connection, post_client
from tests.helpers.request_helpers import build_request


async def run_blocking_inline(func, *args, **kwargs):
    return func(*args, **kwargs)


class McpOAuthRouteTestCase(unittest.TestCase):
    def test_post_client_issues_a_public_client_when_secret_is_not_requested(self):
        request = build_request(
            method="POST",
            path="/api/mcp/oauth/clients",
            json_body={
                "label": "開発用コネクター",
                "redirect_uri": "https://client.example.test/callback",
                "issue_client_secret": False,
            },
            session={"user_id": 7},
        )
        credentials = {"client_id": "mcp-client", "client_secret": None}

        with (
            patch("blueprints.mcp_oauth.is_mcp_enabled", return_value=True),
            patch("blueprints.mcp_oauth.run_blocking", side_effect=run_blocking_inline),
            patch("blueprints.mcp_oauth.issue_user_client", return_value=credentials) as issue_client,
        ):
            response = asyncio.run(post_client(request))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(json.loads(response.body.decode()), credentials)
        issue_client.assert_called_once_with(
            7,
            "開発用コネクター",
            "https://client.example.test/callback",
            False,
        )

    def test_post_client_keeps_legacy_optional_fields_and_secret_default(self):
        request = build_request(
            method="POST",
            path="/api/mcp/oauth/clients",
            json_body={},
            session={"user_id": 7},
        )

        credentials = {"client_id": "mcp-client", "client_secret": "secret"}
        with (
            patch("blueprints.mcp_oauth.is_mcp_enabled", return_value=True),
            patch("blueprints.mcp_oauth.run_blocking", side_effect=run_blocking_inline),
            patch("blueprints.mcp_oauth.issue_user_client", return_value=credentials) as issue_client,
        ):
            response = asyncio.run(post_client(request))

        self.assertEqual(response.status_code, 201)
        issue_client.assert_called_once_with(7, None, None, True)

    def test_patch_client_updates_only_the_authenticated_users_label(self):
        request = build_request(
            method="PATCH",
            path="/api/mcp/oauth/clients/mcp-personal-client",
            json_body={"label": "仕事用コネクター"},
            session={"user_id": 7},
        )

        with (
            patch("blueprints.mcp_oauth.is_mcp_enabled", return_value=True),
            patch("blueprints.mcp_oauth.run_blocking", side_effect=run_blocking_inline),
            patch("blueprints.mcp_oauth.update_user_client_label", return_value=True) as update_label,
        ):
            response = asyncio.run(patch_client("mcp-personal-client", request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode())["message"], "認証情報の名前を更新しました。")
        update_label.assert_called_once_with(7, "mcp-personal-client", "仕事用コネクター")

    def test_patch_connection_updates_display_name_without_replacing_client_name(self):
        request = build_request(
            method="PATCH",
            path="/api/mcp/oauth/connections/grant-1",
            json_body={"display_name": "個人用AI"},
            session={"user_id": 7},
        )

        with (
            patch("blueprints.mcp_oauth.is_mcp_enabled", return_value=True),
            patch("blueprints.mcp_oauth.run_blocking", side_effect=run_blocking_inline),
            patch("blueprints.mcp_oauth.update_connection_display_name", return_value=True) as update_name,
        ):
            response = asyncio.run(patch_connection("grant-1", request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode())["message"], "AIサービスの表示名を更新しました。")
        update_name.assert_called_once_with(7, "grant-1", "個人用AI")

    def test_patch_connection_rejects_non_string_display_name(self):
        request = build_request(
            method="PATCH",
            path="/api/mcp/oauth/connections/grant-1",
            json_body={"display_name": 123},
            session={"user_id": 7},
        )

        with patch("blueprints.mcp_oauth.is_mcp_enabled", return_value=True):
            response = asyncio.run(patch_connection("grant-1", request))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body.decode())["error"], "AIサービスの表示名が不正です。")
