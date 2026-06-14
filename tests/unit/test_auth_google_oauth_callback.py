import unittest

from blueprints.auth import _build_google_authorization_response
from tests.helpers.request_helpers import build_request


def make_request(*, scheme: str, host: str, path: str, query_string: bytes):
    return build_request(
        method="GET",
        scheme=scheme,
        host_header=host,
        path=path,
        query_string=query_string,
    )


class GoogleOAuthCallbackUrlTestCase(unittest.TestCase):
    def test_uses_redirect_uri_origin_for_authorization_response(self):
        request = make_request(
            scheme="http",
            host="internal:5004",
            path="/google-callback",
            query_string=b"code=abc&state=xyz",
        )

        actual = _build_google_authorization_response(
            request, "https://chatcore-ai.com/google-callback"
        )

        self.assertEqual(
            actual,
            "https://chatcore-ai.com/google-callback?code=abc&state=xyz",
        )

    def test_falls_back_to_request_url_when_redirect_uri_is_not_absolute(self):
        request = make_request(
            scheme="http",
            host="localhost:5004",
            path="/google-callback",
            query_string=b"code=devcode",
        )

        actual = _build_google_authorization_response(request, "/google-callback")

        self.assertEqual(actual, "http://localhost:5004/google-callback?code=devcode")


if __name__ == "__main__":
    unittest.main()
