import unittest

from blueprints.auth import _build_google_authorization_response
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


if __name__ == "__main__":
    unittest.main()
