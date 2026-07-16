import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from google_auth_oauthlib.flow import Flow as GoogleOAuthFlow

from blueprints.auth import (
    GOOGLE_CODE_VERIFIER_SESSION_KEY,
    GOOGLE_LOGIN_UNAVAILABLE_ERROR,
    google_callback,
    google_login,
)
from tests.helpers.request_helpers import build_request


# 日本語: テスト用の擬似Fake Flowクラスです。
# English: Mock Fake Flow class for testing.
class FakeFlow:
    # 日本語: 初期化。ダミーの認証情報と認証レスポンス記録用のリストを設定します。
    # English: Initialize. Set dummy credentials and a list to record authorization responses.
    def __init__(self):
        self.credentials = SimpleNamespace(token="google-access-token")
        self.code_verifier = "google-pkce-code-verifier"
        self.authorization_responses = []

    # 日本語: 認可応答を受け取り、トークンを取得します（履歴に記録）。
    # English: Receive authorization response and fetch the token (recorded in history).
    def fetch_token(self, *, authorization_response):
        self.authorization_responses.append(authorization_response)


# 日本語: ブロッキング関数を即時実行するヘルパーです。
# English: Helper to run a blocking function immediately.
async def immediate_run_blocking(func, *args, **kwargs):
    return func(*args, **kwargs)


# 日本語: コールバック用の擬似リクエストを構築します。
# English: Build a mock request for the callback.
def make_request(*, query_string=b"code=abc&state=google-state", session=None):
    request_session = {
        "google_oauth_state": "google-state",
        "google_redirect_uri": "https://chatcore-ai.com/google-callback",
        GOOGLE_CODE_VERIFIER_SESSION_KEY: "google-pkce-code-verifier",
    }
    if session is not None:
        request_session.update(session)
    return build_request(
        method="GET",
        path="/google-callback",
        query_string=query_string,
        session=request_session,
    )


# 日本語: ログイン開始用の擬似リクエストを構築します。
# English: Build a mock request for starting login.
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


# 日本語: 有効なGoogleクライアント設定のダミーデータを返します。
# English: Return valid dummy Google client configuration data.
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


# 日本語: Google Login Flowの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Google Login Flow.
class GoogleLoginFlowTestCase(unittest.TestCase):
    # 日本語: 固定中のgoogle-auth-oauthlibが、復元したPKCE verifierをトークン交換へ渡すことを実ライブラリで検証します。
    # English: Verify with the pinned google-auth-oauthlib that a restored PKCE verifier is forwarded to token exchange.
    def test_google_oauth_library_forwards_restored_pkce_verifier(self):
        redirect_uri = "https://chatcore-ai.com/google-callback"
        start_flow = GoogleOAuthFlow.from_client_config(
            valid_google_client_config(),
            scopes=["openid"],
            redirect_uri=redirect_uri,
            autogenerate_code_verifier=True,
        )
        authorization_url, state = start_flow.authorization_url(prompt="consent")

        self.assertIn("code_challenge=", authorization_url)
        self.assertIsInstance(start_flow.code_verifier, str)
        self.assertGreaterEqual(len(start_flow.code_verifier), 43)

        callback_flow = GoogleOAuthFlow.from_client_config(
            valid_google_client_config(),
            scopes=["openid"],
            state=state,
            redirect_uri=redirect_uri,
            code_verifier=start_flow.code_verifier,
            autogenerate_code_verifier=False,
        )
        with patch.object(
            callback_flow.oauth2session,
            "fetch_token",
            return_value={},
        ) as mock_fetch_token:
            callback_flow.fetch_token(
                authorization_response=f"{redirect_uri}?code=authorization-code&state={state}"
            )

        self.assertEqual(
            mock_fetch_token.call_args.kwargs["code_verifier"],
            start_flow.code_verifier,
        )

    # 日本語: Flowモジュールが欠損している場合、GoogleログインAPIが503を返却することを検証します。
    # English: Verify that google login returns 503 when Flow dependency is missing.
    def test_google_login_returns_503_when_dependency_is_missing(self):
        request = make_google_login_request()

        # 日本語: FlowをNoneにモック化して検証します。
        # English: Mock Flow to None and verify.
        with patch("blueprints.auth.Flow", None):
            response = asyncio.run(google_login(request))

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], GOOGLE_LOGIN_UNAVAILABLE_ERROR)

    # 日本語: OAuthの設定値（client_id等）が欠損している場合、GoogleログインAPIが503を返却することを検証します。
    # English: Verify that google login returns 503 when OAuth configuration values are missing.
    def test_google_login_returns_503_when_oauth_settings_are_missing(self):
        request = make_google_login_request()
        fake_flow_class = Mock()

        # 日本語: 設定値を空にモック化して検証します。
        # English: Mock configuration values to empty and verify.
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

    # 日本語: リクエストのホストが異なる場合、OAuth処理を開始する前に本来のホストへリダイレクトされることを検証します。
    # English: Verify that google login redirects to the correct host before starting OAuth when the request host differs.
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

        # 日本語: リダイレクト先ホストへのリダイレクト発生を確認します。
        # English: Verify that redirection to the target host occurs.
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

    # 日本語: Flowモジュールが欠損している場合、Googleコールバックがログイン画面へリダイレクトすることを検証します。
    # English: Verify that google callback redirects to the login page when Flow dependency is missing.
    def test_google_callback_redirects_to_login_when_dependency_is_missing(self):
        request = make_request()

        # 日本語: FlowをNoneにモック化してコールバックを実行します。
        # English: Mock Flow to None and run callback.
        with patch("blueprints.auth.Flow", None):
            response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/login")

    # 日本語: PKCE verifierがセッションから失われた場合、Googleへのトークン交換を開始せず安全に失敗することを検証します。
    # English: Verify that a missing PKCE verifier fails safely before starting Google's token exchange.
    def test_google_callback_rejects_missing_pkce_code_verifier(self):
        request = build_request(
            method="GET",
            path="/google-callback",
            query_string=b"code=abc&state=google-state",
            session={
                "google_oauth_state": "google-state",
                "google_redirect_uri": "https://chatcore-ai.com/google-callback",
            },
        )
        fake_flow_class = Mock()

        with patch("blueprints.auth.Flow", fake_flow_class):
            response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/login")
        fake_flow_class.from_client_config.assert_not_called()

    # 日本語: クライアント設定からFlowを初期化する際にエラーが発生した場合、503エラーを返すことを検証します。
    # English: Verify that google login returns 503 when initializing the Flow from client config raises an error.
    def test_google_login_returns_503_when_flow_initialization_fails(self):
        request = make_google_login_request()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.side_effect = ValueError("bad oauth config")

        # 日本語: Flow初期化時のエラー発生をシミュレート
        # English: Simulate error occurrence during Flow initialization
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

    # 日本語: ログイン成功時のリダイレクト先(nextパラメータ)がクリーンアップされ、セッションに保存されることを検証します。
    # English: Verify that the next parameter is sanitized and stored in the session.
    def test_google_login_stores_sanitized_next_path_in_session(self):
        request = make_google_login_request(query_string=b"next=%2Fmemo%3Ftab%3Drecent")
        fake_flow = Mock()
        fake_flow.code_verifier = "google-pkce-code-verifier"
        fake_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?state=google-state", "google-state")
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: nextパラメータの保存状態を確認
        # English: Check that the next parameter is stored correctly
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
        self.assertEqual(
            request.session[GOOGLE_CODE_VERIFIER_SESSION_KEY],
            "google-pkce-code-verifier",
        )

    # 日本語: トークン交換に失敗した場合、ログイン画面へリダイレクトされることを検証します。
    # English: Verify that google callback redirects to the login page when token exchange fails.
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

        # 日本語: fetch_tokenエラー発生時のリダイレクト動作とセッション削除動作の検証
        # English: Verify redirection and session cleanup when fetch_token raises ValueError
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
        self.assertNotIn(GOOGLE_CODE_VERIFIER_SESSION_KEY, request.session)
        self.assertNotIn("google_login_next_path", request.session)

    # 日本語: ユーザー情報の取得に失敗した場合、ログイン画面へリダイレクトされることを検証します。
    # English: Verify that google callback redirects to the login page when fetching user info fails.
    def test_google_callback_redirects_to_login_when_userinfo_fetch_fails(self):
        request = make_request()
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: ユーザー情報取得失敗による例外発生を検証
        # English: Verify handling when fetching userinfo raises a RequestException
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

    # 日本語: 初回ログインの際、Googleのプロフィール情報をもとに新規ユーザーが作成されることを検証します。
    # English: Verify that a new user is created using Google profile fields on first login.
    def test_new_google_user_is_created_with_profile_fields(self):
        request = make_request()
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 各種ユーザー作成・連携処理をモック化して検証
        # English: Mock user creation and integration processes to verify behavior
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
        self.assertNotIn(GOOGLE_CODE_VERIFIER_SESSION_KEY, request.session)
        self.assertNotIn("google_login_next_path", request.session)
        self.assertEqual(
            fake_flow.authorization_responses,
            ["https://chatcore-ai.com/google-callback?code=abc&state=google-state"],
        )
        callback_kwargs = fake_flow_class.from_client_config.call_args.kwargs
        self.assertEqual(callback_kwargs["code_verifier"], "google-pkce-code-verifier")
        self.assertFalse(callback_kwargs["autogenerate_code_verifier"])
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

    # 日本語: 同一メールアドレスの既存ユーザー（未検証）が存在する場合、Googleアカウントと連携および検証済みに更新されることを検証します。
    # English: Verify that an existing unverified user with the same email is linked and verified.
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

        # 日本語: アカウント連携および検証処理のモック
        # English: Mock account linkage and verification processes
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
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/?auth=success")
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

    # 日本語: 検証済みの既存ユーザーが初めてGoogleアカウント連携を行った場合も、ログイン画面へ戻さず通常の遷移先へ進むことを検証します。
    # English: Verify that a first Google link for an existing verified email user redirects to the normal destination, not back to login.
    def test_existing_verified_email_user_redirects_to_normal_destination_after_first_google_link(self):
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

        # 日本語: すでに検証済みの既存ユーザーが始めて連携するケースのモック
        # English: Mock first-time link scenario for an already verified user
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
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/?auth=success")
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

    # 日本語: 既存のGoogleユーザーは指定された通常の遷移先へリダイレクトされることを検証します。
    # English: Verify that an existing Google user redirects to the requested normal destination.
    def test_existing_google_user_redirects_to_requested_destination(self):
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

        # 日本語: 二回目以降のログインをモック化して遷移先を確認
        # English: Mock subsequent login and verify target redirect URL
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

    # 日本語: データベースエラーが発生した場合、ログイン画面へリダイレクトされることを検証します。
    # English: Verify that google callback redirects to the login page when a DB error occurs.
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

        # 日本語: DBへの接続エラーをシミュレート
        # English: Simulate connection error to DB
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

    # 日本語: ユーザー作成処理がNoneを返却した場合、ログイン画面へリダイレクトされることを検証します。
    # English: Verify that google callback redirects to login when user creation returns None.
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

        # 日本語: ユーザー作成に失敗するケースのモック
        # English: Mock scenario where user creation returns None
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

    # 日本語: Google側でメールアドレスが未検証の場合、ログイン処理が拒否されることを検証します。
    # English: Verify that google login is rejected if Google reports the email is not verified.
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

        # 日本語: verified_emailがFalseとして返された場合を検証
        # English: Verify handling when verified_email is returned as False
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

    # 日本語: 新規ユーザー作成時に、リダイレクト先(next_path)が正しく引き継がれることを検証します。
    # English: Verify that the redirect path (next_path) is preserved during new user onboarding.
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

        # 日本語: 新規登録処理とリダイレクト先遷移のモック
        # English: Mock registration flow and redirect destination preservation
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

    # 日本語: OIDC準拠のユーザー属性値（sub や email_verified）が返された場合も正しく動作することを検証します。
    # English: Verify that the callback handles OIDC-compliant user info fields (e.g. sub and email_verified).
    def test_handles_oidc_compliant_userinfo_fields(self):
        request = make_request()
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: sub や email_verified が提供されたケースを検証
        # English: Verify handling when sub or email_verified is provided instead of standard fields
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

    # 日本語: Google ID が数値として返された場合でも文字列として処理することを確認します。
    # English: Verify that the callback handles numeric Google IDs by converting them to string.
    def test_handles_numeric_google_id(self):
        request = make_request()
        fake_flow = FakeFlow()
        fake_flow_class = Mock()
        fake_flow_class.from_client_config.return_value = fake_flow

        # 日本語: 数値のIDが渡された場合のパース動作を検証
        # English: Verify parsing when a numeric ID is passed
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
