import asyncio
import unittest
from unittest.mock import Mock, patch

from blueprints.auth import (
    GOOGLE_CODE_VERIFIER_SESSION_KEY,
    _build_google_authorization_response,
    google_callback,
)
from tests.helpers.request_helpers import build_request


# 日本語: Google OAuthコールバックURLテスト用のHTTPリクエストを構築します。
# English: Build an HTTP request for testing Google OAuth callback URL construction.
def make_request(*, scheme: str, host: str, path: str, query_string: bytes):
    return build_request(
        method="GET",
        scheme=scheme,
        host_header=host,
        path=path,
        query_string=query_string,
    )


# 日本語: Google OAuthコールバックURLの組み立てロジックをテストするクラス。
# English: Test class for the Google OAuth callback URL construction logic.
class GoogleOAuthCallbackUrlTestCase(unittest.TestCase):
    # 日本語: redirect_uriが絶対URLの場合、そのオリジンをベースにしてコールバックURLが構築されることを検証します。
    # English: Verify that when redirect_uri is an absolute URL, it is used as the base for the callback URL.
    def test_uses_redirect_uri_origin_for_authorization_response(self):
        # 日本語: 内部ポートでリクエストを構築し、外部の絶対URLを redirect_uri として渡す
        # English: Build a request with an internal port, passing an external absolute URL as redirect_uri
        request = make_request(
            scheme="http",
            host="internal:5004",
            path="/google-callback",
            query_string=b"code=abc&state=xyz",
        )

        actual = _build_google_authorization_response(
            request, "https://chatcore-ai.com/google-callback"
        )

        # 日本語: 外部URLのオリジンにクエリパラメータが付与されたURLになることを確認
        # English: Confirm the result uses the external URL origin with the original query params appended
        self.assertEqual(
            actual,
            "https://chatcore-ai.com/google-callback?code=abc&state=xyz",
        )

    # 日本語: redirect_uriが相対パスの場合、リクエストのURLをベースにしてコールバックURLが構築されることを検証します。
    # English: Verify that when redirect_uri is a relative path, the request URL is used as the base.
    def test_falls_back_to_request_url_when_redirect_uri_is_not_absolute(self):
        # 日本語: ローカルホストでリクエストを構築し、相対パスを redirect_uri として渡す
        # English: Build a request with localhost, passing a relative path as redirect_uri
        request = make_request(
            scheme="http",
            host="localhost:5004",
            path="/google-callback",
            query_string=b"code=devcode",
        )

        actual = _build_google_authorization_response(request, "/google-callback")

        # 日本語: リクエストのホスト情報を使ったURLになることを確認
        # English: Confirm the result is based on the request's own host information
        self.assertEqual(actual, "http://localhost:5004/google-callback?code=devcode")


# 日本語: コールバックがstate照合の先へ進めるよう、妥当なGoogleクライアント設定を返します。
# English: Return a valid Google client configuration so the callback can progress past state verification.
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


# 日本語: レガシーセッション経路のstate照合を検証するテストクラス。
# English: Test class for the legacy session path's OAuth state verification.
class GoogleOAuthCallbackStateVerificationTestCase(unittest.TestCase):
    # 日本語: stateクエリパラメータを省略したコールバックが、照合をすり抜けずに拒否されることを検証します。
    # English: Verify that a callback without the state query parameter is rejected instead of skipping verification.
    def test_rejects_callback_without_state_query_parameter(self):
        # 日本語: セッションにはstateが残っているが、Googleからのstateは付与されていないリクエストを構築
        # English: Build a request whose session still holds a state while the callback carries none
        request = build_request(
            method="GET",
            path="/google-callback",
            query_string=b"code=attacker-code",
            session={
                "google_oauth_state": "google-state",
                "google_redirect_uri": "https://chatcore-ai.com/google-callback",
                GOOGLE_CODE_VERIFIER_SESSION_KEY: "google-pkce-code-verifier",
            },
            scheme="https",
            host_header="chatcore-ai.com",
            server_host="chatcore-ai.com",
            server_port=443,
        )
        fake_flow_class = Mock()

        with patch("blueprints.auth.Flow", fake_flow_class), patch(
            "blueprints.auth._google_client_config",
            side_effect=valid_google_client_config,
        ):
            response = asyncio.run(google_callback(request))

        # 日本語: ログイン画面へ差し戻され、トークン交換が一切開始されないことを確認
        # English: Confirm the user is sent back to the login page and no token exchange is started
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/login")
        fake_flow_class.from_client_config.assert_not_called()
        self.assertNotIn("google_oauth_state", request.session)

    # 日本語: stateが一致しないコールバックも同様に拒否されることを検証します。
    # English: Verify that a callback with a mismatched state is rejected as well.
    def test_rejects_callback_with_mismatched_state(self):
        request = build_request(
            method="GET",
            path="/google-callback",
            query_string=b"code=attacker-code&state=other-state",
            session={
                "google_oauth_state": "google-state",
                "google_redirect_uri": "https://chatcore-ai.com/google-callback",
                GOOGLE_CODE_VERIFIER_SESSION_KEY: "google-pkce-code-verifier",
            },
            scheme="https",
            host_header="chatcore-ai.com",
            server_host="chatcore-ai.com",
            server_port=443,
        )
        fake_flow_class = Mock()

        with patch("blueprints.auth.Flow", fake_flow_class), patch(
            "blueprints.auth._google_client_config",
            side_effect=valid_google_client_config,
        ):
            response = asyncio.run(google_callback(request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/login")
        fake_flow_class.from_client_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
