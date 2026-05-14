import unittest
from unittest.mock import MagicMock, patch

from services import url_fetcher


class ExtractUrlsFromTextTest(unittest.TestCase):
    def test_extracts_http_and_https_urls(self):
        text = "Check https://example.com and http://another.org for more."
        self.assertEqual(
            url_fetcher.extract_urls_from_text(text),
            ["https://example.com", "http://another.org"],
        )

    def test_strips_trailing_punctuation(self):
        text = "See https://example.com/path. And https://other.com/page!"
        self.assertEqual(
            url_fetcher.extract_urls_from_text(text),
            ["https://example.com/path", "https://other.com/page"],
        )

    def test_deduplicates_urls(self):
        text = "https://example.com and https://example.com again"
        self.assertEqual(url_fetcher.extract_urls_from_text(text), ["https://example.com"])

    def test_limits_to_max_urls(self):
        text = " ".join(f"https://site{i}.com" for i in range(10))
        self.assertEqual(
            len(url_fetcher.extract_urls_from_text(text)),
            url_fetcher.MAX_URLS_PER_MESSAGE,
        )

    def test_returns_empty_for_no_urls(self):
        self.assertEqual(url_fetcher.extract_urls_from_text("No URLs here."), [])

    def test_ignores_non_http_schemes(self):
        self.assertEqual(
            url_fetcher.extract_urls_from_text("ftp://example.com and mailto:user@x.com"),
            [],
        )

    def test_preserves_query_strings(self):
        url = "https://example.com/search?q=hello&lang=ja"
        self.assertEqual(url_fetcher.extract_urls_from_text(url), [url])

    def test_strips_trailing_closing_paren(self):
        text = "See (https://example.com)"
        result = url_fetcher.extract_urls_from_text(text)
        self.assertEqual(result, ["https://example.com"])


class IsSafeUrlTest(unittest.TestCase):
    def test_allows_public_ip(self):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            self.assertTrue(url_fetcher._is_safe_url("https://example.com"))

    def test_blocks_loopback(self):
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://somehost.com"))

    def test_blocks_private_10_network(self):
        with patch("socket.gethostbyname", return_value="10.0.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://internal.corp"))

    def test_blocks_private_172_network(self):
        with patch("socket.gethostbyname", return_value="172.20.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://internal.corp"))

    def test_blocks_private_192_168_network(self):
        with patch("socket.gethostbyname", return_value="192.168.1.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://router.local"))

    def test_blocks_link_local_cloud_metadata(self):
        with patch("socket.gethostbyname", return_value="169.254.169.254"):
            self.assertFalse(url_fetcher._is_safe_url("https://metadata.example.com"))

    def test_blocks_localhost_hostname(self):
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("http://localhost/admin"))

    def test_blocks_non_http_scheme(self):
        self.assertFalse(url_fetcher._is_safe_url("ftp://example.com"))

    def test_returns_false_on_dns_error(self):
        with patch("socket.gethostbyname", side_effect=OSError("NXDOMAIN")):
            self.assertFalse(url_fetcher._is_safe_url("https://nonexistent.invalid"))

    def test_returns_false_for_empty_hostname(self):
        self.assertFalse(url_fetcher._is_safe_url("https:///path"))


class ExtractTextFromHtmlTest(unittest.TestCase):
    def test_extracts_body_text(self):
        html = "<html><body><h1>Title</h1><p>Some text.</p></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertIn("Title", result)
        self.assertIn("Some text.", result)

    def test_removes_script_content(self):
        html = "<html><body><p>Hello</p><script>alert('xss')</script></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertIn("Hello", result)
        self.assertNotIn("alert", result)

    def test_removes_style_content(self):
        html = "<html><head><style>body{color:red}</style></head><body><p>Text</p></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotIn("color", result)
        self.assertIn("Text", result)

    def test_removes_nav_content(self):
        html = "<html><body><nav>Menu</nav><main><p>Content</p></main></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotIn("Menu", result)
        self.assertIn("Content", result)

    def test_collapses_excessive_blank_lines(self):
        html = "<html><body>" + "<p>x</p>" * 5 + "</body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotRegex(result, r"\n{3,}")

    def test_handles_nested_skip_tags(self):
        html = "<script><script>inner</script></script><p>After</p>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotIn("inner", result)
        self.assertIn("After", result)

    def test_decodes_html_entities(self):
        html = "<p>Hello &amp; World &lt;3&gt;</p>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertIn("Hello & World", result)

    def test_empty_html_returns_empty_string(self):
        self.assertEqual(url_fetcher._extract_text_from_html(""), "")


class FetchUrlContentTest(unittest.TestCase):
    def _make_response(
        self,
        content: bytes,
        content_type: str = "text/html; charset=utf-8",
        status_code: int = 200,
        headers: dict | None = None,
    ) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        merged_headers = {"content-type": content_type}
        if headers:
            merged_headers.update(headers)
        resp.headers = merged_headers
        resp.apparent_encoding = "utf-8"
        resp.iter_content.return_value = iter([content])
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        return resp

    def test_returns_text_for_valid_html_url(self):
        resp = self._make_response(b"<html><body><p>Hello world</p></body></html>")
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Hello world", result)

    def test_returns_text_for_plain_text_url(self):
        resp = self._make_response(b"Plain text here.", content_type="text/plain")
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com/readme.txt")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Plain text here.", result)

    def test_returns_none_for_unsafe_url(self):
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            result = url_fetcher.fetch_url_content("http://localhost/admin")
        self.assertIsNone(result)

    def test_returns_none_for_non_text_content_type(self):
        resp = self._make_response(b"%PDF-1.4", content_type="application/pdf")
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com/doc.pdf")
        self.assertIsNone(result)

    def test_returns_none_on_http_error(self):
        resp = self._make_response(b"", status_code=404)
        resp.raise_for_status.side_effect = Exception("404 Not Found")
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com/missing")
        self.assertIsNone(result)

    def test_returns_none_on_connection_error(self):
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", side_effect=ConnectionError("timeout")),
        ):
            result = url_fetcher.fetch_url_content("https://example.com")
        self.assertIsNone(result)

    def test_truncates_content_to_max_chars(self):
        long_body = b"<p>" + b"A" * (url_fetcher.MAX_URL_TEXT_CHARS + 5000) + b"</p>"
        resp = self._make_response(long_body)
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertLessEqual(len(result), url_fetcher.MAX_URL_TEXT_CHARS)

    def test_returns_none_for_empty_extracted_text(self):
        resp = self._make_response(b"<html><body></body></html>")
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com")
        self.assertIsNone(result)


class FetchUrlRedirectTest(unittest.TestCase):
    def _redirect_response(self, location: str, status: int = 302) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        resp.headers = {"Location": location, "content-type": "text/html"}
        resp.apparent_encoding = "utf-8"
        resp.iter_content.return_value = iter([b""])
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        return resp

    def _ok_response(self, body: bytes = b"<p>final</p>") -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"content-type": "text/html; charset=utf-8"}
        resp.apparent_encoding = "utf-8"
        resp.iter_content.return_value = iter([body])
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        return resp

    def test_rejects_redirect_to_internal_address(self):
        redirect = self._redirect_response("http://169.254.169.254/latest/meta-data/")

        def resolver(host):
            return {
                "example.com": "93.184.216.34",
                "169.254.169.254": "169.254.169.254",
            }[host]

        with (
            patch("socket.gethostbyname", side_effect=resolver),
            patch("requests.get", return_value=redirect) as mock_get,
        ):
            result = url_fetcher.fetch_url_content("https://example.com")

        self.assertIsNone(result)
        # The metadata service must never have been contacted.
        self.assertEqual(mock_get.call_count, 1)
        called_url = mock_get.call_args_list[0].args[0]
        self.assertEqual(called_url, "https://example.com")

    def test_follows_safe_redirect_chain(self):
        responses = iter(
            [
                self._redirect_response("https://b.example.com/next"),
                self._ok_response(b"<p>done</p>"),
            ]
        )

        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", side_effect=lambda *a, **k: next(responses)),
        ):
            result = url_fetcher.fetch_url_content("https://a.example.com")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("done", result)

    def test_aborts_redirect_loop_after_max_hops(self):
        def loop(*args, **kwargs):
            return self._redirect_response("https://loop.example.com/again")

        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", side_effect=loop) as mock_get,
        ):
            result = url_fetcher.fetch_url_content("https://loop.example.com")

        self.assertIsNone(result)
        self.assertLessEqual(mock_get.call_count, url_fetcher.MAX_REDIRECT_HOPS + 1)

    def test_disables_auto_redirects_at_request_level(self):
        captured: dict = {}

        def capture(*args, **kwargs):
            captured["kwargs"] = kwargs
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"content-type": "text/html"}
            resp.apparent_encoding = "utf-8"
            resp.iter_content.return_value = iter([b"<p>x</p>"])
            resp.raise_for_status = MagicMock()
            resp.close = MagicMock()
            return resp

        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", side_effect=capture),
        ):
            url_fetcher.fetch_url_content("https://example.com")

        self.assertIs(captured["kwargs"].get("allow_redirects"), False)


class DnsPinningTest(unittest.TestCase):
    def test_pinned_create_connection_replaces_host_with_validated_ip(self):
        calls: list[tuple] = []

        def fake_create_connection(address, *args, **kwargs):
            calls.append(address)
            return object()

        with patch.object(
            url_fetcher,
            "_original_urllib3_create_connection",
            side_effect=fake_create_connection,
        ):
            with url_fetcher._pin_dns({"example.com": "93.184.216.34"}):
                url_fetcher._pinned_create_connection(("example.com", 443))

        self.assertEqual(calls, [("93.184.216.34", 443)])

    def test_pinned_create_connection_passes_through_when_unpinned(self):
        calls: list[tuple] = []

        def fake_create_connection(address, *args, **kwargs):
            calls.append(address)
            return object()

        with patch.object(
            url_fetcher,
            "_original_urllib3_create_connection",
            side_effect=fake_create_connection,
        ):
            url_fetcher._pinned_create_connection(("other.example.com", 80))

        self.assertEqual(calls, [("other.example.com", 80)])

    def test_pin_dns_restores_previous_mapping(self):
        with url_fetcher._pin_dns({"a": "1.1.1.1"}):
            with url_fetcher._pin_dns({"b": "2.2.2.2"}):
                self.assertEqual(
                    getattr(url_fetcher._dns_pin_local, "mapping", None),
                    {"b": "2.2.2.2"},
                )
            self.assertEqual(
                getattr(url_fetcher._dns_pin_local, "mapping", None),
                {"a": "1.1.1.1"},
            )
        self.assertIsNone(getattr(url_fetcher._dns_pin_local, "mapping", None))


class FetchUrlsContentTest(unittest.TestCase):
    def test_returns_mapping_of_successful_fetches(self):
        with patch.object(url_fetcher, "fetch_url_content", side_effect=["text-a", None, "text-c"]):
            result = url_fetcher.fetch_urls_content(
                ["https://a.com", "https://b.com", "https://c.com"]
            )
        self.assertEqual(result, {"https://a.com": "text-a", "https://c.com": "text-c"})

    def test_returns_empty_dict_when_all_fail(self):
        with patch.object(url_fetcher, "fetch_url_content", return_value=None):
            result = url_fetcher.fetch_urls_content(["https://example.com"])
        self.assertEqual(result, {})

    def test_returns_empty_dict_for_empty_input(self):
        self.assertEqual(url_fetcher.fetch_urls_content([]), {})
