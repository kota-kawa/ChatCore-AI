import unittest
from unittest.mock import MagicMock, patch

from services import url_fetcher


# 日本語: ExtractUrlsFromTextTest のテストケースをまとめます。
# English: Group test cases for ExtractUrlsFromTextTest.
class ExtractUrlsFromTextTest(unittest.TestCase):
    # 日本語: test extracts http and https urls のテスト検証を担当します。
    # English: Handle verifying test behavior for test extracts http and https urls.
    def test_extracts_http_and_https_urls(self):
        text = "Check https://example.com and http://another.org for more."
        self.assertEqual(
            url_fetcher.extract_urls_from_text(text),
            ["https://example.com", "http://another.org"],
        )

    # 日本語: test strips trailing punctuation のテスト検証を担当します。
    # English: Handle verifying test behavior for test strips trailing punctuation.
    def test_strips_trailing_punctuation(self):
        text = "See https://example.com/path. And https://other.com/page!"
        self.assertEqual(
            url_fetcher.extract_urls_from_text(text),
            ["https://example.com/path", "https://other.com/page"],
        )

    # 日本語: test deduplicates urls のテスト検証を担当します。
    # English: Handle verifying test behavior for test deduplicates urls.
    def test_deduplicates_urls(self):
        text = "https://example.com and https://example.com again"
        self.assertEqual(url_fetcher.extract_urls_from_text(text), ["https://example.com"])

    # 日本語: test limits to max urls のテスト検証を担当します。
    # English: Handle verifying test behavior for test limits to max urls.
    def test_limits_to_max_urls(self):
        text = " ".join(f"https://site{i}.com" for i in range(10))
        self.assertEqual(
            len(url_fetcher.extract_urls_from_text(text)),
            url_fetcher.MAX_URLS_PER_MESSAGE,
        )

    # 日本語: test returns empty for no urls のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns empty for no urls.
    def test_returns_empty_for_no_urls(self):
        self.assertEqual(url_fetcher.extract_urls_from_text("No URLs here."), [])

    # 日本語: test ignores non http schemes のテスト検証を担当します。
    # English: Handle verifying test behavior for test ignores non http schemes.
    def test_ignores_non_http_schemes(self):
        self.assertEqual(
            url_fetcher.extract_urls_from_text("ftp://example.com and mailto:user@x.com"),
            [],
        )

    # 日本語: test preserves query strings のテスト検証を担当します。
    # English: Handle verifying test behavior for test preserves query strings.
    def test_preserves_query_strings(self):
        url = "https://example.com/search?q=hello&lang=ja"
        self.assertEqual(url_fetcher.extract_urls_from_text(url), [url])

    # 日本語: test strips trailing closing paren のテスト検証を担当します。
    # English: Handle verifying test behavior for test strips trailing closing paren.
    def test_strips_trailing_closing_paren(self):
        text = "See (https://example.com)"
        result = url_fetcher.extract_urls_from_text(text)
        self.assertEqual(result, ["https://example.com"])


# 日本語: IsSafeUrlTest のテストケースをまとめます。
# English: Group test cases for IsSafeUrlTest.
class IsSafeUrlTest(unittest.TestCase):
    # 日本語: test allows public ip のテスト検証を担当します。
    # English: Handle verifying test behavior for test allows public ip.
    def test_allows_public_ip(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            self.assertTrue(url_fetcher._is_safe_url("https://example.com"))

    # 日本語: test blocks loopback のテスト検証を担当します。
    # English: Handle verifying test behavior for test blocks loopback.
    def test_blocks_loopback(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://somehost.com"))

    # 日本語: test blocks private 10 network のテスト検証を担当します。
    # English: Handle verifying test behavior for test blocks private 10 network.
    def test_blocks_private_10_network(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("socket.gethostbyname", return_value="10.0.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://internal.corp"))

    # 日本語: test blocks private 172 network のテスト検証を担当します。
    # English: Handle verifying test behavior for test blocks private 172 network.
    def test_blocks_private_172_network(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("socket.gethostbyname", return_value="172.20.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://internal.corp"))

    # 日本語: test blocks private 192 168 network のテスト検証を担当します。
    # English: Handle verifying test behavior for test blocks private 192 168 network.
    def test_blocks_private_192_168_network(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("socket.gethostbyname", return_value="192.168.1.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://router.local"))

    # 日本語: test blocks link local cloud metadata のテスト検証を担当します。
    # English: Handle verifying test behavior for test blocks link local cloud metadata.
    def test_blocks_link_local_cloud_metadata(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("socket.gethostbyname", return_value="169.254.169.254"):
            self.assertFalse(url_fetcher._is_safe_url("https://metadata.example.com"))

    # 日本語: test blocks localhost hostname のテスト検証を担当します。
    # English: Handle verifying test behavior for test blocks localhost hostname.
    def test_blocks_localhost_hostname(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("http://localhost/admin"))

    # 日本語: test blocks non http scheme のテスト検証を担当します。
    # English: Handle verifying test behavior for test blocks non http scheme.
    def test_blocks_non_http_scheme(self):
        self.assertFalse(url_fetcher._is_safe_url("ftp://example.com"))

    # 日本語: test returns false on dns error のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns false on dns error.
    def test_returns_false_on_dns_error(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("socket.gethostbyname", side_effect=OSError("NXDOMAIN")):
            self.assertFalse(url_fetcher._is_safe_url("https://nonexistent.invalid"))

    # 日本語: test returns false for empty hostname のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns false for empty hostname.
    def test_returns_false_for_empty_hostname(self):
        self.assertFalse(url_fetcher._is_safe_url("https:///path"))


# 日本語: ExtractTextFromHtmlTest のテストケースをまとめます。
# English: Group test cases for ExtractTextFromHtmlTest.
class ExtractTextFromHtmlTest(unittest.TestCase):
    # 日本語: test extracts body text のテスト検証を担当します。
    # English: Handle verifying test behavior for test extracts body text.
    def test_extracts_body_text(self):
        html = "<html><body><h1>Title</h1><p>Some text.</p></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertIn("Title", result)
        self.assertIn("Some text.", result)

    # 日本語: test removes script content のテスト検証を担当します。
    # English: Handle verifying test behavior for test removes script content.
    def test_removes_script_content(self):
        html = "<html><body><p>Hello</p><script>alert('xss')</script></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertIn("Hello", result)
        self.assertNotIn("alert", result)

    # 日本語: test removes style content のテスト検証を担当します。
    # English: Handle verifying test behavior for test removes style content.
    def test_removes_style_content(self):
        html = "<html><head><style>body{color:red}</style></head><body><p>Text</p></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotIn("color", result)
        self.assertIn("Text", result)

    # 日本語: test removes nav content のテスト検証を担当します。
    # English: Handle verifying test behavior for test removes nav content.
    def test_removes_nav_content(self):
        html = "<html><body><nav>Menu</nav><main><p>Content</p></main></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotIn("Menu", result)
        self.assertIn("Content", result)

    # 日本語: test collapses excessive blank lines のテスト検証を担当します。
    # English: Handle verifying test behavior for test collapses excessive blank lines.
    def test_collapses_excessive_blank_lines(self):
        html = "<html><body>" + "<p>x</p>" * 5 + "</body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotRegex(result, r"\n{3,}")

    # 日本語: test handles nested skip tags のテスト検証を担当します。
    # English: Handle verifying test behavior for test handles nested skip tags.
    def test_handles_nested_skip_tags(self):
        html = "<script><script>inner</script></script><p>After</p>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotIn("inner", result)
        self.assertIn("After", result)

    # 日本語: test decodes html entities のテスト検証を担当します。
    # English: Handle verifying test behavior for test decodes html entities.
    def test_decodes_html_entities(self):
        html = "<p>Hello &amp; World &lt;3&gt;</p>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertIn("Hello & World", result)

    # 日本語: test empty html returns empty string のテスト検証を担当します。
    # English: Handle verifying test behavior for test empty html returns empty string.
    def test_empty_html_returns_empty_string(self):
        self.assertEqual(url_fetcher._extract_text_from_html(""), "")


# 日本語: FetchUrlContentTest のテストケースをまとめます。
# English: Group test cases for FetchUrlContentTest.
class FetchUrlContentTest(unittest.TestCase):
    # 日本語: make response の生成処理を担当します。
    # English: Handle creating for make response.
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
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if headers:
            merged_headers.update(headers)
        resp.headers = merged_headers
        resp.apparent_encoding = "utf-8"
        resp.iter_content.return_value = iter([content])
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        return resp

    # 日本語: test returns text for valid html url のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns text for valid html url.
    def test_returns_text_for_valid_html_url(self):
        resp = self._make_response(b"<html><body><p>Hello world</p></body></html>")
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Hello world", result)

    # 日本語: test returns text for plain text url のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns text for plain text url.
    def test_returns_text_for_plain_text_url(self):
        resp = self._make_response(b"Plain text here.", content_type="text/plain")
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com/readme.txt")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Plain text here.", result)

    # 日本語: test returns none for unsafe url のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns none for unsafe url.
    def test_returns_none_for_unsafe_url(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            result = url_fetcher.fetch_url_content("http://localhost/admin")
        self.assertIsNone(result)

    # 日本語: test returns none for non text content type のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns none for non text content type.
    def test_returns_none_for_non_text_content_type(self):
        resp = self._make_response(b"%PDF-1.4", content_type="application/pdf")
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com/doc.pdf")
        self.assertIsNone(result)

    # 日本語: test returns none on http error のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns none on http error.
    def test_returns_none_on_http_error(self):
        resp = self._make_response(b"", status_code=404)
        resp.raise_for_status.side_effect = Exception("404 Not Found")
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com/missing")
        self.assertIsNone(result)

    # 日本語: test returns none on connection error のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns none on connection error.
    def test_returns_none_on_connection_error(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", side_effect=ConnectionError("timeout")),
        ):
            result = url_fetcher.fetch_url_content("https://example.com")
        self.assertIsNone(result)

    # 日本語: test truncates content to max chars のテスト検証を担当します。
    # English: Handle verifying test behavior for test truncates content to max chars.
    def test_truncates_content_to_max_chars(self):
        long_body = b"<p>" + b"A" * (url_fetcher.MAX_URL_TEXT_CHARS + 5000) + b"</p>"
        resp = self._make_response(long_body)
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertLessEqual(len(result), url_fetcher.MAX_URL_TEXT_CHARS)

    # 日本語: test returns none for empty extracted text のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns none for empty extracted text.
    def test_returns_none_for_empty_extracted_text(self):
        resp = self._make_response(b"<html><body></body></html>")
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com")
        self.assertIsNone(result)


# 日本語: FetchUrlRedirectTest のテストケースをまとめます。
# English: Group test cases for FetchUrlRedirectTest.
class FetchUrlRedirectTest(unittest.TestCase):
    # 日本語: redirect response に関する処理の入口です。
    # English: Entry point for logic related to redirect response.
    def _redirect_response(self, location: str, status: int = 302) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        resp.headers = {"Location": location, "content-type": "text/html"}
        resp.apparent_encoding = "utf-8"
        resp.iter_content.return_value = iter([b""])
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        return resp

    # 日本語: ok response に関する処理の入口です。
    # English: Entry point for logic related to ok response.
    def _ok_response(self, body: bytes = b"<p>final</p>") -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"content-type": "text/html; charset=utf-8"}
        resp.apparent_encoding = "utf-8"
        resp.iter_content.return_value = iter([body])
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        return resp

    # 日本語: test rejects redirect to internal address のテスト検証を担当します。
    # English: Handle verifying test behavior for test rejects redirect to internal address.
    def test_rejects_redirect_to_internal_address(self):
        redirect = self._redirect_response("http://169.254.169.254/latest/meta-data/")

        # 日本語: resolver に関する処理の入口です。
        # English: Entry point for logic related to resolver.
        def resolver(host):
            return {
                "example.com": "93.184.216.34",
                "169.254.169.254": "169.254.169.254",
            }[host]

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test follows safe redirect chain のテスト検証を担当します。
    # English: Handle verifying test behavior for test follows safe redirect chain.
    def test_follows_safe_redirect_chain(self):
        responses = iter(
            [
                self._redirect_response("https://b.example.com/next"),
                self._ok_response(b"<p>done</p>"),
            ]
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", side_effect=lambda *a, **k: next(responses)),
        ):
            result = url_fetcher.fetch_url_content("https://a.example.com")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("done", result)

    # 日本語: test aborts redirect loop after max hops のテスト検証を担当します。
    # English: Handle verifying test behavior for test aborts redirect loop after max hops.
    def test_aborts_redirect_loop_after_max_hops(self):
        # 日本語: loop に関する処理の入口です。
        # English: Entry point for logic related to loop.
        def loop(*args, **kwargs):
            return self._redirect_response("https://loop.example.com/again")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", side_effect=loop) as mock_get,
        ):
            result = url_fetcher.fetch_url_content("https://loop.example.com")

        self.assertIsNone(result)
        self.assertLessEqual(mock_get.call_count, url_fetcher.MAX_REDIRECT_HOPS + 1)

    # 日本語: test disables auto redirects at request level のテスト検証を担当します。
    # English: Handle verifying test behavior for test disables auto redirects at request level.
    def test_disables_auto_redirects_at_request_level(self):
        captured: dict = {}

        # 日本語: capture に関する処理の入口です。
        # English: Entry point for logic related to capture.
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

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", side_effect=capture),
        ):
            url_fetcher.fetch_url_content("https://example.com")

        self.assertIs(captured["kwargs"].get("allow_redirects"), False)


# 日本語: DnsPinningTest のテストケースをまとめます。
# English: Group test cases for DnsPinningTest.
class DnsPinningTest(unittest.TestCase):
    # 日本語: test pinned create connection replaces host with validated ip のテスト検証を担当します。
    # English: Handle verifying test behavior for test pinned create connection replaces host with validated ip.
    def test_pinned_create_connection_replaces_host_with_validated_ip(self):
        calls: list[tuple] = []

        # 日本語: fake create connection に関する処理の入口です。
        # English: Entry point for logic related to fake create connection.
        def fake_create_connection(address, *args, **kwargs):
            calls.append(address)
            return object()

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(
            url_fetcher,
            "_original_urllib3_create_connection",
            side_effect=fake_create_connection,
        ):
            with url_fetcher._pin_dns({"example.com": "93.184.216.34"}):
                url_fetcher._pinned_create_connection(("example.com", 443))

        self.assertEqual(calls, [("93.184.216.34", 443)])

    # 日本語: test pinned create connection passes through when unpinned のテスト検証を担当します。
    # English: Handle verifying test behavior for test pinned create connection passes through when unpinned.
    def test_pinned_create_connection_passes_through_when_unpinned(self):
        calls: list[tuple] = []

        # 日本語: fake create connection に関する処理の入口です。
        # English: Entry point for logic related to fake create connection.
        def fake_create_connection(address, *args, **kwargs):
            calls.append(address)
            return object()

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(
            url_fetcher,
            "_original_urllib3_create_connection",
            side_effect=fake_create_connection,
        ):
            url_fetcher._pinned_create_connection(("other.example.com", 80))

        self.assertEqual(calls, [("other.example.com", 80)])

    # 日本語: test pin dns restores previous mapping のテスト検証を担当します。
    # English: Handle verifying test behavior for test pin dns restores previous mapping.
    def test_pin_dns_restores_previous_mapping(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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


# 日本語: FetchUrlsContentTest のテストケースをまとめます。
# English: Group test cases for FetchUrlsContentTest.
class FetchUrlsContentTest(unittest.TestCase):
    # 日本語: test returns mapping of successful fetches のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns mapping of successful fetches.
    def test_returns_mapping_of_successful_fetches(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(url_fetcher, "fetch_url_content", side_effect=["text-a", None, "text-c"]):
            result = url_fetcher.fetch_urls_content(
                ["https://a.com", "https://b.com", "https://c.com"]
            )
        self.assertEqual(result, {"https://a.com": "text-a", "https://c.com": "text-c"})

    # 日本語: test returns empty dict when all fail のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns empty dict when all fail.
    def test_returns_empty_dict_when_all_fail(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(url_fetcher, "fetch_url_content", return_value=None):
            result = url_fetcher.fetch_urls_content(["https://example.com"])
        self.assertEqual(result, {})

    # 日本語: test returns empty dict for empty input のテスト検証を担当します。
    # English: Handle verifying test behavior for test returns empty dict for empty input.
    def test_returns_empty_dict_for_empty_input(self):
        self.assertEqual(url_fetcher.fetch_urls_content([]), {})
