import unittest
from unittest.mock import MagicMock, patch

from services import url_fetcher


# テキストメッセージからURLを抽出する関数の挙動（HTTP/HTTPSスキーム、重複排除、文字制限、末尾の記号削除など）をテストするクラス。
# Test class to check the behavior of the URL extraction function from text messages.
class ExtractUrlsFromTextTest(unittest.TestCase):
    # HTTPおよびHTTPSのURLが正しく抽出されることを検証します。
    # Verify that HTTP and HTTPS URLs are correctly extracted.
    def test_extracts_http_and_https_urls(self):
        text = "Check https://example.com and http://another.org for more."
        self.assertEqual(
            url_fetcher.extract_urls_from_text(text),
            ["https://example.com", "http://another.org"],
        )

    # URLの末尾に句読点などの記号がついている場合、それらを除去して抽出されることを検証します。
    # Verify that trailing punctuation marks are stripped from the extracted URLs.
    def test_strips_trailing_punctuation(self):
        text = "See https://example.com/path. And https://other.com/page!"
        self.assertEqual(
            url_fetcher.extract_urls_from_text(text),
            ["https://example.com/path", "https://other.com/page"],
        )

    # 重複するURLが自動的に排除され、ユニークなURLのみが抽出されることを検証します。
    # Verify that duplicate URLs are automatically deduplicated.
    def test_deduplicates_urls(self):
        text = "https://example.com and https://example.com again"
        self.assertEqual(url_fetcher.extract_urls_from_text(text), ["https://example.com"])

    # 1つのメッセージから抽出される最大URL数が制限内に収まることを検証します。
    # Verify that the number of extracted URLs does not exceed the allowed maximum.
    def test_limits_to_max_urls(self):
        text = " ".join(f"https://site{i}.com" for i in range(10))
        self.assertEqual(
            len(url_fetcher.extract_urls_from_text(text)),
            url_fetcher.MAX_URLS_PER_MESSAGE,
        )

    # URLが含まれていない場合、空のリストが返ることを検証します。
    # Verify that an empty list is returned when there are no URLs in the text.
    def test_returns_empty_for_no_urls(self):
        self.assertEqual(url_fetcher.extract_urls_from_text("No URLs here."), [])

    # HTTP/HTTPS以外のスキーム（FTPやmailto等）が無視されることを検証します。
    # Verify that non-HTTP/HTTPS schemes (such as FTP or mailto) are ignored.
    def test_ignores_non_http_schemes(self):
        self.assertEqual(
            url_fetcher.extract_urls_from_text("ftp://example.com and mailto:user@x.com"),
            [],
        )

    # URL内のクエリストリングが欠落せず維持されることを検証します。
    # Verify that query strings in URLs are preserved correctly.
    def test_preserves_query_strings(self):
        url = "https://example.com/search?q=hello&lang=ja"
        self.assertEqual(url_fetcher.extract_urls_from_text(url), [url])

    # URLが丸括弧で囲まれている場合、末尾の閉じ括弧が除去されることを検証します。
    # Verify that trailing closing parentheses are stripped from the extracted URLs.
    def test_strips_trailing_closing_paren(self):
        text = "See (https://example.com)"
        result = url_fetcher.extract_urls_from_text(text)
        self.assertEqual(result, ["https://example.com"])


# SSRF（Server-Side Request Forgery）対策としてのURL安全性チェック（ローカルIPやプライベートIP、リンクローカル、DNSエラー等のブロック）をテストするクラス。
# Test class to verify URL safety checks (blocking local, private, and link-local IPs) to prevent SSRF.
class IsSafeUrlTest(unittest.TestCase):
    # パブリック（グローバル）IPを持つ安全なURLが許可されることを検証します。
    # Verify that URLs resolving to public IPs are allowed.
    def test_allows_public_ip(self):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            self.assertTrue(url_fetcher._is_safe_url("https://example.com"))

    # ループバックアドレス（127.0.0.1）に解決されるURLが拒否されることを検証します。
    # Verify that URLs resolving to loopback addresses (127.0.0.1) are blocked.
    def test_blocks_loopback(self):
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://somehost.com"))

    # プライベートネットワーク（10.0.0.0/8）のIPに解決されるURLが拒否されることを検証します。
    # Verify that URLs resolving to private 10.x.x.x addresses are blocked.
    def test_blocks_private_10_network(self):
        with patch("socket.gethostbyname", return_value="10.0.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://internal.corp"))

    # プライベートネットワーク（172.16.0.0/12）のIPに解決されるURLが拒否されることを検証します。
    # Verify that URLs resolving to private 172.16.x.x - 172.31.x.x addresses are blocked.
    def test_blocks_private_172_network(self):
        with patch("socket.gethostbyname", return_value="172.20.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://internal.corp"))

    # プライベートネットワーク（192.168.0.0/16）のIPに解決されるURLが拒否されることを検証します。
    # Verify that URLs resolving to private 192.168.x.x addresses are blocked.
    def test_blocks_private_192_168_network(self):
        with patch("socket.gethostbyname", return_value="192.168.1.1"):
            self.assertFalse(url_fetcher._is_safe_url("https://router.local"))

    # クラウドのリンクローカルメタデータアドレス（169.254.169.254）が拒否されることを検証します。
    # Verify that link-local addresses (e.g. cloud metadata services) are blocked.
    def test_blocks_link_local_cloud_metadata(self):
        with patch("socket.gethostbyname", return_value="169.254.169.254"):
            self.assertFalse(url_fetcher._is_safe_url("https://metadata.example.com"))

    # ホスト名が直接 "localhost" の場合に拒否されることを検証します。
    # Verify that URLs with hostnames directly resolving to localhost are blocked.
    def test_blocks_localhost_hostname(self):
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            self.assertFalse(url_fetcher._is_safe_url("http://localhost/admin"))

    # HTTP/HTTPS以外のスキームが安全性チェックで弾かれることを検証します。
    # Verify that safety checks block non-HTTP/HTTPS URLs.
    def test_blocks_non_http_scheme(self):
        self.assertFalse(url_fetcher._is_safe_url("ftp://example.com"))

    # DNSの名前解決エラー（NXDOMAIN等）が発生した場合に、安全でないと判断されることを検証します。
    # Verify that URLs causing DNS errors are treated as unsafe.
    def test_returns_false_on_dns_error(self):
        with patch("socket.gethostbyname", side_effect=OSError("NXDOMAIN")):
            self.assertFalse(url_fetcher._is_safe_url("https://nonexistent.invalid"))

    # ホスト名部分が空のURLは拒否されることを検証します。
    # Verify that URLs with empty hostnames are blocked.
    def test_returns_false_for_empty_hostname(self):
        self.assertFalse(url_fetcher._is_safe_url("https:///path"))


# HTML文書から本文テキストをクリーンに抽出する処理（スクリプト、スタイル、ナビゲーションタグの除外やHTMLエンティティのデコード等）をテストするクラス。
# Test class to check HTML text extraction and cleanup logic (excluding scripts, styles, navs, and decoding entities).
class ExtractTextFromHtmlTest(unittest.TestCase):
    # HTMLボディ内のテキスト本文が適切に抽出されることを検証します。
    # Verify that main body text is successfully extracted from HTML.
    def test_extracts_body_text(self):
        html = "<html><body><h1>Title</h1><p>Some text.</p></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertIn("Title", result)
        self.assertIn("Some text.", result)

    # <script>タグとその中身のJSコードが抽出対象から除外されることを検証します。
    # Verify that script tags and their inner javascript content are removed.
    def test_removes_script_content(self):
        html = "<html><body><p>Hello</p><script>alert('xss')</script></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertIn("Hello", result)
        self.assertNotIn("alert", result)

    # <style>タグとその中身のCSSスタイル定義が抽出対象から除外されることを検証します。
    # Verify that style tags and their inner CSS properties are removed.
    def test_removes_style_content(self):
        html = "<html><head><style>body{color:red}</style></head><body><p>Text</p></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotIn("color", result)
        self.assertIn("Text", result)

    # <nav>タグなどのナビゲーション用コンテンツが抽出対象から除外されることを検証します。
    # Verify that nav sections containing menus/links are excluded.
    def test_removes_nav_content(self):
        html = "<html><body><nav>Menu</nav><main><p>Content</p></main></body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotIn("Menu", result)
        self.assertIn("Content", result)

    # テキスト抽出の際に、連続した過剰な改行が崩されずに collapse されることを検証します。
    # Verify that excessive consecutive blank lines are collapsed.
    def test_collapses_excessive_blank_lines(self):
        html = "<html><body>" + "<p>x</p>" * 5 + "</body></html>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotRegex(result, r"\n{3,}")

    # 入れ子になったスクリプトタグが含まれている場合でも、内部のコンテンツごと無視されることを検証します。
    # Verify that nested script tags and all their contents are correctly ignored.
    def test_handles_nested_skip_tags(self):
        html = "<script><script>inner</script></script><p>After</p>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertNotIn("inner", result)
        self.assertIn("After", result)

    # HTMLエンティティ（&amp; や &lt; 等）がデコードされた文字列として取得されることを検証します。
    # Verify that HTML entities are successfully decoded to plain characters.
    def test_decodes_html_entities(self):
        html = "<p>Hello &amp; World &lt;3&gt;</p>"
        result = url_fetcher._extract_text_from_html(html)
        self.assertIn("Hello & World", result)

    # 空のHTMLを渡した場合に、空文字列が返ることを検証します。
    # Verify that an empty HTML input returns an empty string.
    def test_empty_html_returns_empty_string(self):
        self.assertEqual(url_fetcher._extract_text_from_html(""), "")


# 単一のURLからコンテンツをフェッチする機能（正常取得、例外処理、不正なコンテンツタイプの拒否、文字数制限等）をテストするクラス。
# Test class for fetching content from a single URL (handling exceptions, content-type checks, and truncating size).
class FetchUrlContentTest(unittest.TestCase):
    # テスト用の疑似HTTPレスポンスオブジェクトを構築します。
    # Build a mock HTTP response object for testing.
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

    # 正常なHTMLのURLからテキストコンテンツがフェッチされることを検証します。
    # Verify that text content is fetched successfully from a valid HTML page URL.
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

    # プレーンテキストのURLからテキストコンテンツがそのままフェッチされることを検証します。
    # Verify that plain text content is fetched successfully from a text file URL.
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

    # 安全でないと判定されたホスト（localhostなど）からのフェッチ要求がNoneを返すことを検証します。
    # Verify that fetching from an unsafe host/IP resolves to None.
    def test_returns_none_for_unsafe_url(self):
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            result = url_fetcher.fetch_url_content("http://localhost/admin")
        self.assertIsNone(result)

    # テキスト系以外のコンテンツタイプ（PDF等）のフェッチ要求がNoneを返すことを検証します。
    # Verify that fetching non-text Content-Types (e.g. PDF) resolves to None.
    def test_returns_none_for_non_text_content_type(self):
        resp = self._make_response(b"%PDF-1.4", content_type="application/pdf")
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com/doc.pdf")
        self.assertIsNone(result)

    # HTTPレスポンスエラー（404等）が発生した際、例外を起こさずNoneが返却されることを検証します。
    # Verify that HTTP error responses (e.g. 404) result in returning None.
    def test_returns_none_on_http_error(self):
        resp = self._make_response(b"", status_code=404)
        resp.raise_for_status.side_effect = Exception("404 Not Found")
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com/missing")
        self.assertIsNone(result)

    # ネットワーク接続エラーが発生した際、例外を起こさずNoneが返却されることを検証します。
    # Verify that connection errors result in returning None.
    def test_returns_none_on_connection_error(self):
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", side_effect=ConnectionError("timeout")),
        ):
            result = url_fetcher.fetch_url_content("https://example.com")
        self.assertIsNone(result)

    # 取得したコンテンツが最大制限文字数を超えている場合、制限サイズに切り詰められることを検証します。
    # Verify that fetched text content exceeding the maximum length is truncated.
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

    # HTMLから何もテキストが抽出されなかった（空ボディ等）場合に、Noneが返却されることを検証します。
    # Verify that returning None when the HTML yields no textual content.
    def test_returns_none_for_empty_extracted_text(self):
        resp = self._make_response(b"<html><body></body></html>")
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("requests.get", return_value=resp),
        ):
            result = url_fetcher.fetch_url_content("https://example.com")
        self.assertIsNone(result)


# リダイレクトを伴うフェッチ処理（SSRF防止のための遷移先IP検証、リダイレクトループの中断、安全なリダイレクトの追従等）をテストするクラス。
# Test class to check redirects during URL fetching, ensuring SSRF protection, loop prevention, and safe traversal.
class FetchUrlRedirectTest(unittest.TestCase):
    # テスト用の疑似リダイレクト応答オブジェクトを構築します。
    # Build a mock redirect HTTP response object.
    def _redirect_response(self, location: str, status: int = 302) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        resp.headers = {"Location": location, "content-type": "text/html"}
        resp.apparent_encoding = "utf-8"
        resp.iter_content.return_value = iter([b""])
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        return resp

    # テスト用の疑似正常応答オブジェクトを構築します。
    # Build a mock OK HTTP response object.
    def _ok_response(self, body: bytes = b"<p>final</p>") -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"content-type": "text/html; charset=utf-8"}
        resp.apparent_encoding = "utf-8"
        resp.iter_content.return_value = iter([body])
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        return resp

    # リダイレクト先としてプライベートIP/リンクローカルIPなどの安全でないアドレスが指定された際、リクエストが中止されNoneが返ることを検証します。
    # Verify that redirects leading to unsafe/private IPs are blocked and return None.
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
        # 危険なメタデータサーバーへのリクエストは一度も発生していないことを検証
        # The metadata service must never have been contacted.
        self.assertEqual(mock_get.call_count, 1)
        called_url = mock_get.call_args_list[0].args[0]
        self.assertEqual(called_url, "https://example.com")

    # 安全なリダイレクト先への遷移である場合、チェーンを正しく追従して最終応答が得られることを検証します。
    # Verify that a safe redirect chain is successfully traversed to fetch the final content.
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

    # リダイレクトループが発生している場合、最大制限ホップ数を超えたところで自動的に中断しNoneを返すことを検証します。
    # Verify that redirect loops are aborted after reaching the maximum redirect limit, returning None.
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

    # 自動リダイレクト追従（requestsのデフォルトの動き）が、リクエストレベルで明示的に無効化(allow_redirects=False)されていることを検証します。
    # Verify that requests are called with allow_redirects=False to manually control the redirect chain validation.
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


# TOCTOU（Time-of-Check to Time-of-Use）脆弱性を防ぐためのDNSピニング（IPアドレス固定）機能の挙動をテストするクラス。
# Test class to check DNS pinning logic, protecting against TOCTOU vulnerability during URL fetching.
class DnsPinningTest(unittest.TestCase):
    # DNSピニングのスコープ内において、元の接続作成時にホスト名が事前検証済みのIPアドレスに置換されることを検証します。
    # Verify that hostnames are replaced with the pre-validated pinned IP addresses when establishing connections.
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

    # ピニング対象外のホストに対する接続要求の場合、元のホスト情報のままスルーして処理されることを検証します。
    # Verify that connection requests to unpinned hostnames pass through unchanged.
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

    # DNSピニング処理コンテキストのネストにおいて、各スコープ終了時に以前のマッピング定義が正しく復元されることを検証します。
    # Verify that nested DNS pinning contexts correctly restore their respective parent mappings on exit.
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


# 複数のURLからまとめてコンテンツをフェッチし、成功した結果のみをマッピングして返す関数をテストするクラス。
# Test class to check batch fetching of contents from multiple URLs and mapping successful results.
class FetchUrlsContentTest(unittest.TestCase):
    # 複数URLのフェッチ処理において、成功したURLのみを取得内容とマッピングした辞書として返却されることを検証します。
    # Verify that a dictionary mapping of only successfully fetched URLs to their text contents is returned.
    def test_returns_mapping_of_successful_fetches(self):
        with patch.object(url_fetcher, "fetch_url_content", side_effect=["text-a", None, "text-c"]):
            result = url_fetcher.fetch_urls_content(
                ["https://a.com", "https://b.com", "https://c.com"]
            )
        self.assertEqual(result, {"https://a.com": "text-a", "https://c.com": "text-c"})

    # 全てのURLフェッチが失敗した際に、例外を起こさず空の辞書が返却されることを検証します。
    # Verify that an empty dictionary is returned if all URL fetches fail.
    def test_returns_empty_dict_when_all_fail(self):
        with patch.object(url_fetcher, "fetch_url_content", return_value=None):
            result = url_fetcher.fetch_urls_content(["https://example.com"])
        self.assertEqual(result, {})

    # 入力URLリストが空の場合に、空の辞書が即座に返却されることを検証します。
    # Verify that passing an empty list returns an empty dictionary immediately.
    def test_returns_empty_dict_for_empty_input(self):
        self.assertEqual(url_fetcher.fetch_urls_content([]), {})
