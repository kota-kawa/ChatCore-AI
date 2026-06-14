import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from blueprints.auth import (
    GOOGLE_LOGIN_UNAVAILABLE_ERROR,
    google_callback,
    google_login,
)
from tests.helpers.request_helpers import build_request


# 日本語: FakeFlow に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeFlow.
class FakeFlow:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        self.credentials = SimpleNamespace(token="google-access-token")
        self.authorization_responses = []

    # 日本語: fetch token の取得処理を担当します。
    # English: Handle fetching for fetch token.
    def fetch_token(self, *, authorization_response):
        self.authorization_responses.append(authorization_response)


# 日本語: immediate run blocking に関する処理の入口です。
# English: Entry point for logic related to immediate run blocking.
async def immediate_run_blocking(func, *args, **kwargs):
    return func(*args, **kwargs)


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
def make_request(*, query_string=b"code=abc&state=google-state", session=None):
    return build_request(
        method="GET",
        path="/google-callback",
        query_string=query_string,
        session=session
        or {
            "google_oauth_state": "google-state",
            "google_redirect_uri": "https://chatcore-ai.com/google-callback",
        },
    )


# 日本語: make google login request の生成処理を担当します。
# English: Handle creating for make google login request.
def make_google_login_request(*, query_string=b"", session=None):
    return build_request(
        method="GET",
        path="/google-login",
        query_string=query_string,
        session=session or {},
        scheme="https",
        host_header="chatcore-ai.com",
        server_host="chatcore-ai.com",
        server_port=443,
    )


# 日本語: valid google client config に関する処理の入口です。
# English: Entry point for logic related to valid google client config.
def valid_google_client_config():
    return {
        "web": {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [],
            "javascript_origins": ["https://chatcore-ai.com"],
        }
    }


# 日本語: GoogleLoginFlowTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to GoogleLoginFlowTestCase.
class GoogleLoginFlowTestCase(unittest.TestCase):
    # 日本語: test google login returns 503 when dependency is missing のテスト検証を担当します。
    # English: Handle verifying test behavior for test google login returns 503 when dependency is missing.
    def test_google_login_returns_503_when_dependency_is_missing(self):
        request = make_google_login_request()

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", None):
            response = asyncio.run(google_login(request))

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], GOOGLE_LOGIN_UNAVAILABLE_ERROR)

    # 日本語: test google login returns 503 when oauth settings are missing のテスト検証を担当します。
    # English: Handle verifying test behavior for test google login returns 503 when oauth settings are missing.
    def test_google_login_returns_503_when_oauth_settings_are_missing(self):
        request = make_google_login_request()
        fake_flow_class = Mock()

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                return_value={
                    "web": {
                        "client_id": "",
                        "client_secret": "",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": [],
                        "javascript_origins": ["https://chatcore-ai.com"],
                    }
                },
            ):
                with patch(
                    "blueprints.auth.url_for",
                    return_value="https://chatcore-ai.com/google-callback",
                ):
                    response = asyncio.run(google_login(request))

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], GOOGLE_LOGIN_UNAVAILABLE_ERROR)
        fake_flow_class.from_client_config.assert_not_called()

    # 日本語: test google login redirects to redirect uri host before starting oauth のテスト検証を担当します。
    # English: Handle verifying test behavior for test google login redirects to redirect uri host before starting oauth.
    def test_google_login_redirects_to_redirect_uri_host_before_starting_oauth(self):
        request = build_request(
            method="GET",
            path="/google-login",
            session={},
            scheme="https",
            host_header="www.chatcore-ai.com",
            server_host="www.chatcore-ai.com",
            server_port=443,
        )
        fake_flow_class = Mock()

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch.dict(
                    "os.environ",
                    {"GOOGLE_REDIRECT_URI": "https://chatcore-ai.com/google-callback"},
                    clear=False,
                ):
                    response = asyncio.run(google_login(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/google-login")
        self.assertEqual(request.session, {})
        fake_flow_class.from_client_config.assert_not_called()

    # 日本語: test google callback redirects to login when dependency is missing のテスト検証を担当します。
    # English: Handle verifying test behavior for test google callback redirects to login when dependency is missing.
    def test_google_callback_redirects_to_login_when_dependency_is_missing(self):
        request = make_request()

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", None):
            response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/login")

    # 日本語: test google login returns 503 when flow initialization fails のテスト検証を担当します。
    # English: Handle verifying test behavior for test google login returns 503 when flow initialization fails.
    def test_google_login_returns_503_when_flow_initialization_fails(self):
        request = make_google_login_request()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.side_effect = ValueError("bad oauth config")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch(
                    "blueprints.auth.url_for",
                    return_value="https://chatcore-ai.com/google-callback",
                ):
                    response = asyncio.run(google_login(request))

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], GOOGLE_LOGIN_UNAVAILABLE_ERROR)

    # 日本語: test google login stores sanitized next path in session のテスト検証を担当します。
    # English: Handle verifying test behavior for test google login stores sanitized next path in session.
    def test_google_login_stores_sanitized_next_path_in_session(self):
        request = make_google_login_request(query_string=b"next=%2Fmemo%3Ftab%3Drecent")
        fake_flow = Mock()
        fake_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?state=google-state", "google-state")
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch(
                    "blueprints.auth.url_for",
                    return_value="https://chatcore-ai.com/google-callback",
                ):
                    response = asyncio.run(google_login(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["location"],
            "https://accounts.google.com/o/oauth2/auth?state=google-state",
        )
        self.assertEqual(request.session["google_login_next_path"], "/memo?tab=recent")

    # 日本語: test google callback redirects to login when token exchange fails のテスト検証を担当します。
    # English: Handle verifying test behavior for test google callback redirects to login when token exchange fails.
    def test_google_callback_redirects_to_login_when_token_exchange_fails(self):
        request = make_request(
            session={
                "google_oauth_state": "google-state",
                "google_redirect_uri": "https://chatcore-ai.com/google-callback",
                "google_login_next_path": "/memo",
            }
        )
        fake_flow = FakeFlow()
        fake_flow.fetch_token = Mock(side_effect=ValueError("invalid_grant"))
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/login?next=%2Fmemo")
        self.assertNotIn("google_oauth_state", request.session)
        self.assertNotIn("google_redirect_uri", request.session)
        self.assertNotIn("google_login_next_path", request.session)

    # 日本語: test google callback redirects to login when userinfo fetch fails のテスト検証を担当します。
    # English: Handle verifying test behavior for test google callback redirects to login when userinfo fetch fails.
    def test_google_callback_redirects_to_login_when_userinfo_fetch_fails(self):
        request = make_request()
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        side_effect=requests.RequestException("provider down"),
                    ):
                        response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/login")
        self.assertNotIn("user_id", request.session)

    # 日本語: test new google user is created with profile fields のテスト検証を担当します。
    # English: Handle verifying test behavior for test new google user is created with profile fields.
    def test_new_google_user_is_created_with_profile_fields(self):
        request = make_request()
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        return_value={
                            "id": "google-user-123",
                            "email": "user@example.com",
                            "verified_email": True,
                            "name": "Alice Example",
                            "picture": "https://example.com/alice.png",
                        },
                    ):
                        with patch("blueprints.auth.get_user_by_google_id", return_value=None):
                            with patch("blueprints.auth.get_user_by_email", return_value=None):
                                with patch("blueprints.auth.create_user", return_value=42) as mock_create:
                                    with patch("blueprints.auth.link_google_account") as mock_link:
                                        with patch(
                                            "blueprints.auth.update_user_profile_from_google_if_unset"
                                        ) as mock_profile_sync:
                                            with patch("blueprints.auth.set_user_verified") as mock_verify:
                                                with patch(
                                                    "blueprints.auth.copy_default_tasks_for_user"
                                                ) as mock_copy_tasks:
                                                    with patch(
                                                        "blueprints.auth.get_user_by_id",
                                                        return_value={
                                                            "id": 42,
                                                            "email": "user@example.com",
                                                        },
                                                    ):
                                                        with patch(
                                                            "blueprints.auth.frontend_url",
                                                            return_value="http://frontend/",
                                                        ) as mock_frontend_url:
                                                            response = asyncio.run(
                                                                google_callback(request)
                                                            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["location"],
            "https://chatcore-ai.com/?auth=success",
        )
        mock_frontend_url.assert_not_called()
        self.assertEqual(request.session["user_id"], 42)
        self.assertEqual(request.session["user_email"], "user@example.com")
        self.assertNotIn("google_oauth_state", request.session)
        self.assertNotIn("google_redirect_uri", request.session)
        self.assertNotIn("google_login_next_path", request.session)
        self.assertEqual(
            fake_flow.authorization_responses,
            ["https://chatcore-ai.com/google-callback?code=abc&state=google-state"],
        )
        mock_create.assert_called_once_with(
            "user@example.com",
            username="Alice Example",
            avatar_url="https://example.com/alice.png",
            auth_provider="google",
            provider_user_id="google-user-123",
            provider_email="user@example.com",
            is_verified=True,
        )
        mock_link.assert_not_called()
        mock_profile_sync.assert_called_once_with(
            42,
            "Alice Example",
            "https://example.com/alice.png",
        )
        mock_verify.assert_not_called()
        mock_copy_tasks.assert_called_once_with(42)

    # 日本語: test existing email user is linked and verified のテスト検証を担当します。
    # English: Handle verifying test behavior for test existing email user is linked and verified.
    def test_existing_email_user_is_linked_and_verified(self):
        request = make_request()
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow
        existing_user = {
            "id": 7,
            "email": "user@example.com",
            "is_verified": False,
            "provider_user_id": None,
            "username": "Custom Name",
            "avatar_url": "/static/uploads/custom.png",
        }

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        return_value={
                            "id": "google-user-123",
                            "email": "user@example.com",
                            "verified_email": True,
                            "name": "Alice Example",
                            "picture": "https://example.com/alice.png",
                        },
                    ):
                        with patch("blueprints.auth.get_user_by_google_id", return_value=None):
                            with patch(
                                "blueprints.auth.get_user_by_email",
                                return_value=existing_user,
                            ):
                                with patch("blueprints.auth.create_user") as mock_create:
                                    with patch("blueprints.auth.link_google_account") as mock_link:
                                        with patch(
                                            "blueprints.auth.update_user_profile_from_google_if_unset"
                                        ) as mock_profile_sync:
                                            with patch(
                                                "blueprints.auth.set_user_verified"
                                            ) as mock_verify:
                                                with patch(
                                                    "blueprints.auth.copy_default_tasks_for_user"
                                                ) as mock_copy_tasks:
                                                    with patch(
                                                        "blueprints.auth.get_user_by_id",
                                                        return_value={
                                                            "id": 7,
                                                            "email": "user@example.com",
                                                        },
                                                    ):
                                                        response = asyncio.run(
                                                            google_callback(request)
                                                        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["location"],
            "https://chatcore-ai.com/login?flow=register&offer_passkey_setup=1&provider=google",
        )
        self.assertEqual(request.session["user_id"], 7)
        mock_create.assert_not_called()
        mock_link.assert_called_once_with(7, "google-user-123", "user@example.com")
        mock_profile_sync.assert_called_once_with(
            7,
            "Alice Example",
            "https://example.com/alice.png",
        )
        mock_verify.assert_called_once_with(7)
        mock_copy_tasks.assert_called_once_with(7)

    # 日本語: test existing verified email user is prompted for passkey after first google link のテスト検証を担当します。
    # English: Handle verifying test behavior for test existing verified email user is prompted for passkey after first google link.
    def test_existing_verified_email_user_is_prompted_for_passkey_after_first_google_link(self):
        request = make_request()
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow
        existing_user = {
            "id": 8,
            "email": "user@example.com",
            "is_verified": True,
            "provider_user_id": None,
            "username": "Custom Name",
            "avatar_url": "/static/uploads/custom.png",
        }

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        return_value={
                            "id": "google-user-456",
                            "email": "user@example.com",
                            "verified_email": True,
                            "name": "Alice Example",
                            "picture": "https://example.com/alice.png",
                        },
                    ):
                        with patch("blueprints.auth.get_user_by_google_id", return_value=None):
                            with patch(
                                "blueprints.auth.get_user_by_email",
                                return_value=existing_user,
                            ):
                                with patch("blueprints.auth.create_user") as mock_create:
                                    with patch("blueprints.auth.link_google_account") as mock_link:
                                        with patch(
                                            "blueprints.auth.update_user_profile_from_google_if_unset"
                                        ) as mock_profile_sync:
                                            with patch(
                                                "blueprints.auth.set_user_verified"
                                            ) as mock_verify:
                                                with patch(
                                                    "blueprints.auth.copy_default_tasks_for_user"
                                                ) as mock_copy_tasks:
                                                    with patch(
                                                        "blueprints.auth.get_user_by_id",
                                                        return_value={
                                                            "id": 8,
                                                            "email": "user@example.com",
                                                        },
                                                    ):
                                                        response = asyncio.run(
                                                            google_callback(request)
                                                        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["location"],
            "https://chatcore-ai.com/login?flow=register&offer_passkey_setup=1&provider=google",
        )
        self.assertEqual(request.session["user_id"], 8)
        mock_create.assert_not_called()
        mock_link.assert_called_once_with(8, "google-user-456", "user@example.com")
        mock_profile_sync.assert_called_once_with(
            8,
            "Alice Example",
            "https://example.com/alice.png",
        )
        mock_verify.assert_not_called()
        mock_copy_tasks.assert_called_once_with(8)

    # 日本語: test existing google user keeps normal redirect after passkey prompt was already shown のテスト検証を担当します。
    # English: Handle verifying test behavior for test existing google user keeps normal redirect after passkey prompt was already shown.
    def test_existing_google_user_keeps_normal_redirect_after_passkey_prompt_was_already_shown(self):
        request = make_request(
            session={
                "google_oauth_state": "google-state",
                "google_redirect_uri": "https://chatcore-ai.com/google-callback",
                "google_login_next_path": "/memo",
            }
        )
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow
        existing_google_user = {
            "id": 9,
            "email": "user@example.com",
            "is_verified": True,
            "provider_user_id": "google-user-789",
            "username": "Alice Example",
            "avatar_url": "https://example.com/alice.png",
        }

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        return_value={
                            "id": "google-user-789",
                            "email": "user@example.com",
                            "verified_email": True,
                            "name": "Alice Example",
                            "picture": "https://example.com/alice.png",
                        },
                    ):
                        with patch(
                            "blueprints.auth.get_user_by_google_id",
                            return_value=existing_google_user,
                        ):
                            with patch("blueprints.auth.link_google_account") as mock_link:
                                with patch(
                                    "blueprints.auth.update_user_profile_from_google_if_unset"
                                ):
                                    with patch("blueprints.auth.set_user_verified") as mock_verify:
                                        with patch(
                                            "blueprints.auth.copy_default_tasks_for_user"
                                        ):
                                            with patch(
                                                "blueprints.auth.get_user_by_id",
                                                return_value={
                                                    "id": 9,
                                                    "email": "user@example.com",
                                                },
                                            ):
                                                response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/memo")
        mock_link.assert_called_once_with(9, "google-user-789", "user@example.com")
        mock_verify.assert_not_called()

    # 日本語: test google callback redirects to login when db error occurs のテスト検証を担当します。
    # English: Handle verifying test behavior for test google callback redirects to login when db error occurs.
    def test_google_callback_redirects_to_login_when_db_error_occurs(self):
        request = make_request(
            session={
                "google_oauth_state": "google-state",
                "google_redirect_uri": "https://chatcore-ai.com/google-callback",
                "google_login_next_path": "/memo",
            }
        )
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        return_value={
                            "id": "google-user-123",
                            "email": "user@example.com",
                            "verified_email": True,
                            "name": "Alice",
                            "picture": "https://example.com/alice.png",
                        },
                    ):
                        with patch(
                            "blueprints.auth.get_user_by_google_id",
                            side_effect=Exception("DB connection error"),
                        ):
                            response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/login?next=%2Fmemo")
        self.assertNotIn("user_id", request.session)

    # 日本語: test google callback redirects to login when create user returns none のテスト検証を担当します。
    # English: Handle verifying test behavior for test google callback redirects to login when create user returns none.
    def test_google_callback_redirects_to_login_when_create_user_returns_none(self):
        request = make_request(
            session={
                "google_oauth_state": "google-state",
                "google_redirect_uri": "https://chatcore-ai.com/google-callback",
                "google_login_next_path": "/memo",
            }
        )
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        return_value={
                            "id": "google-user-123",
                            "email": "user@example.com",
                            "verified_email": True,
                            "name": "Alice",
                            "picture": "https://example.com/alice.png",
                        },
                    ):
                        with patch("blueprints.auth.get_user_by_google_id", return_value=None):
                            with patch("blueprints.auth.get_user_by_email", return_value=None):
                                with patch("blueprints.auth.create_user", return_value=None):
                                    response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/login?next=%2Fmemo")
        self.assertNotIn("user_id", request.session)

    # 日本語: test rejects google login when email is not verified のテスト検証を担当します。
    # English: Handle verifying test behavior for test rejects google login when email is not verified.
    def test_rejects_google_login_when_email_is_not_verified(self):
        request = make_request(
            session={
                "google_oauth_state": "google-state",
                "google_redirect_uri": "https://chatcore-ai.com/google-callback",
                "google_login_next_path": "/memo",
            }
        )
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        return_value={
                            "id": "google-user-123",
                            "email": "user@example.com",
                            "verified_email": False,
                        },
                    ):
                        with patch("blueprints.auth.create_user") as mock_create:
                            response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/login?next=%2Fmemo")
        mock_create.assert_not_called()
        self.assertNotIn("user_id", request.session)

    # 日本語: test new google user onboarding preserves next path のテスト検証を担当します。
    # English: Handle verifying test behavior for test new google user onboarding preserves next path.
    def test_new_google_user_onboarding_preserves_next_path(self):
        request = make_request(
            session={
                "google_oauth_state": "google-state",
                "google_redirect_uri": "https://chatcore-ai.com/google-callback",
                "google_login_next_path": "/memo?tab=recent",
            }
        )
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        return_value={
                            "id": "google-user-123",
                            "email": "user@example.com",
                            "verified_email": True,
                            "name": "Alice Example",
                        },
                    ):
                        with patch("blueprints.auth.get_user_by_google_id", return_value=None):
                            with patch("blueprints.auth.get_user_by_email", return_value=None):
                                with patch("blueprints.auth.create_user", return_value=42):
                                    with patch("blueprints.auth.update_user_profile_from_google_if_unset"):
                                        with patch("blueprints.auth.copy_default_tasks_for_user"):
                                            with patch(
                                                "blueprints.auth.get_user_by_id",
                                                return_value={"id": 42, "email": "user@example.com"},
                                            ):
                                                response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["location"],
            "https://chatcore-ai.com/memo?tab=recent",
        )

    # 日本語: test handles oidc compliant userinfo fields のテスト検証を担当します。
    # English: Handle verifying test behavior for test handles oidc compliant userinfo fields.
    def test_handles_oidc_compliant_userinfo_fields(self):
        # sub や email_verified が使用されている場合でも正しく動作することを確認
        request = make_request()
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        return_value={
                            "sub": "google-oidc-456",
                            "email": "oidc@example.com",
                            "email_verified": True,
                            "name": "OIDC User",
                        },
                    ):
                        with patch("blueprints.auth.get_user_by_google_id", return_value=None):
                            with patch("blueprints.auth.get_user_by_email", return_value=None):
                                with patch("blueprints.auth.create_user", return_value=99) as mock_create:
                                    with patch("blueprints.auth.get_user_by_id", return_value={"id": 99, "email": "oidc@example.com"}):
                                        with patch("blueprints.auth.update_user_profile_from_google_if_unset"):
                                            with patch("blueprints.auth.copy_default_tasks_for_user"):
                                                response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(request.session["user_id"], 99)
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        self.assertEqual(kwargs["provider_user_id"], "google-oidc-456")

    # 日本語: test handles numeric google id のテスト検証を担当します。
    # English: Handle verifying test behavior for test handles numeric google id.
    def test_handles_numeric_google_id(self):
        # Google ID が数値として返された場合でも文字列として処理することを確認
        request = make_request()
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.Flow", fake_flow_class):
            with patch(
                "blueprints.auth._google_client_config",
                side_effect=valid_google_client_config,
            ):
                with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                    with patch(
                        "blueprints.auth._fetch_google_user_info",
                        return_value={
                            "id": 123456789,
                            "email": "numeric@example.com",
                            "verified_email": True,
                        },
                    ):
                        with patch("blueprints.auth.get_user_by_google_id", return_value=None):
                            with patch("blueprints.auth.get_user_by_email", return_value=None):
                                with patch("blueprints.auth.create_user", return_value=100) as mock_create:
                                    with patch("blueprints.auth.get_user_by_id", return_value={"id": 100, "email": "numeric@example.com"}):
                                        with patch("blueprints.auth.update_user_profile_from_google_if_unset"):
                                            with patch("blueprints.auth.copy_default_tasks_for_user"):
                                                response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(request.session["user_id"], 100)
        args, kwargs = mock_create.call_args
        self.assertEqual(kwargs["provider_user_id"], "123456789")


if __name__ == "__main__":
    unittest.main()
