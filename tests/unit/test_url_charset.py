import codecs
import unittest

from services import url_charset


# 受信済みバイト列から文字コードを解決するロジック（BOM・ヘッダー宣言・meta宣言・推定の優先順位）をテストするクラス。
# Test class for charset resolution from received bytes (BOM, header, meta, detection precedence).
class ResolveCharsetTest(unittest.TestCase):
    # Content-Type ヘッダーの charset パラメータが使用されることを検証します。
    # Verify the Content-Type header's charset parameter is used.
    def test_uses_content_type_header_charset(self):
        resolved = url_charset.resolve_charset(
            "こんにちは".encode("euc-jp"),
            content_type="text/html; charset=euc-jp",
        )
        self.assertEqual(resolved, codecs.lookup("euc-jp").name)

    # charset の値が引用符付きでも解釈できることを検証します。
    # Verify a quoted charset value is still parsed.
    def test_parses_quoted_charset_value(self):
        resolved = url_charset.resolve_charset(
            b"hello",
            content_type='text/html; charset="shift_jis"',
        )
        self.assertEqual(resolved, codecs.lookup("shift_jis").name)

    # HTML の meta 宣言が使用されることを検証します。
    # Verify the in-document HTML meta declaration is used.
    def test_uses_html_meta_charset(self):
        raw = "<html><head><meta charset='shift_jis'></head><body>本文</body></html>".encode(
            "shift_jis"
        )
        resolved = url_charset.resolve_charset(raw, content_type="text/html", is_html=True)
        self.assertEqual(resolved, codecs.lookup("shift_jis").name)

    # http-equiv 形式の meta 宣言も解釈できることを検証します。
    # Verify the http-equiv form of the meta declaration is parsed too.
    def test_uses_http_equiv_meta_charset(self):
        raw = (
            b"<html><head><meta http-equiv=\"Content-Type\" "
            b"content=\"text/html; charset=euc-jp\"></head></html>"
        )
        resolved = url_charset.resolve_charset(raw, content_type="text/html", is_html=True)
        self.assertEqual(resolved, codecs.lookup("euc-jp").name)

    # HTMLでないコンテンツでは meta 宣言を参照しないことを検証します。
    # Verify meta declarations are ignored for non-HTML content.
    def test_ignores_meta_charset_for_non_html(self):
        raw = "<meta charset='shift_jis'> 実際はUTF-8のプレーンテキスト".encode("utf-8")
        resolved = url_charset.resolve_charset(raw, content_type="text/plain", is_html=False)
        self.assertEqual(resolved, codecs.lookup("utf-8").name)
        # HTML として扱った場合は同じ宣言が使われることを対比で確認する
        # Contrast: the same declaration is honored when the body is treated as HTML.
        self.assertEqual(
            url_charset.resolve_charset(raw, content_type="text/html", is_html=True),
            codecs.lookup("shift_jis").name,
        )

    # 宣言が無くUTF-8として解釈できる本文は、統計的推定より優先してUTF-8と判定されることを検証します。
    # Verify undeclared bodies that decode cleanly as UTF-8 win over statistical detection.
    def test_prefers_strict_utf8_over_detection_for_undeclared_body(self):
        raw = "宣言のない日本語ページ本文です。".encode("utf-8")
        self.assertEqual(url_charset.resolve_charset(raw), codecs.lookup("utf-8").name)

    # 末尾が途中で切れたUTF-8本文でも、推定へ落ちずUTF-8と判定されることを検証します。
    # Verify a UTF-8 body truncated mid-character is still resolved as UTF-8.
    def test_treats_truncated_utf8_body_as_utf8(self):
        raw = "打ち切られた日本語本文".encode("utf-8")[:-1]
        self.assertEqual(url_charset.resolve_charset(raw), codecs.lookup("utf-8").name)

    # UTF-8として解釈できない本文では統計的推定へフォールバックすることを検証します。
    # Verify bodies that are not valid UTF-8 fall back to statistical detection.
    def test_falls_back_to_detection_for_non_utf8_body(self):
        # 統計的推定はサンプルが短いと外れるため、実ページ相当の長さで検証する
        # Statistical detection needs a realistic sample size to be reliable.
        text = "本日は晴天なり。日本語のページ本文がシフトJISで配信されている状況を想定した検証用の文章です。" * 20
        raw = text.encode("shift_jis")
        resolved = url_charset.resolve_charset(raw)
        self.assertNotEqual(resolved, codecs.lookup("utf-8").name)
        self.assertEqual(raw.decode(resolved), text)

    # BOM がヘッダー宣言より優先されることを検証します。
    # Verify a BOM takes precedence over the header declaration.
    def test_bom_takes_precedence_over_header(self):
        raw = codecs.BOM_UTF8 + "テキスト".encode("utf-8")
        resolved = url_charset.resolve_charset(raw, content_type="text/html; charset=euc-jp")
        self.assertEqual(resolved, codecs.lookup("utf-8-sig").name)

    # UTF-32 の BOM が UTF-16 と誤判定されないことを検証します。
    # Verify a UTF-32 BOM is not mistaken for UTF-16.
    def test_detects_utf32_bom_over_utf16_prefix(self):
        raw = codecs.BOM_UTF32_LE + "ab".encode("utf-32-le")
        resolved = url_charset.resolve_charset(raw)
        self.assertEqual(resolved, codecs.lookup("utf-32-le").name)

    # 実在しない文字コード名が宣言された場合に無視されることを検証します。
    # Verify an unknown charset name is ignored.
    def test_ignores_unknown_charset_name(self):
        resolved = url_charset.resolve_charset(
            b"hello world",
            content_type="text/html; charset=not-a-real-codec",
        )
        self.assertEqual(resolved, codecs.lookup("utf-8").name)

    # 宣言が一切無い場合に既定値へフォールバックすることを検証します。
    # Verify the fallback encoding is used when nothing is declared.
    def test_falls_back_to_utf8_without_declarations(self):
        resolved = url_charset.resolve_charset(b"", content_type="")
        self.assertEqual(resolved, "utf-8")


# 受信済みバイト列を文字列へデコードする処理をテストするクラス。
# Test class for decoding received bytes into text.
class DecodeResponseBodyTest(unittest.TestCase):
    # 宣言された文字コードで正しくデコードされることを検証します。
    # Verify the body decodes using the declared charset.
    def test_decodes_declared_charset(self):
        raw = "日本語テキスト".encode("euc-jp")
        result = url_charset.decode_response_body(
            raw, content_type="text/html; charset=euc-jp", is_html=True
        )
        self.assertEqual(result, "日本語テキスト")

    # BOM 付き UTF-8 のデコード結果に BOM が残らないことを検証します。
    # Verify the BOM is stripped from decoded UTF-8 text.
    def test_strips_utf8_bom(self):
        raw = codecs.BOM_UTF8 + "本文".encode("utf-8")
        self.assertEqual(url_charset.decode_response_body(raw), "本文")

    # サイズ上限で途中打ち切りされたマルチバイト文字があっても例外にならないことを検証します。
    # Verify decoding does not raise when a multibyte character is truncated by the size cap.
    def test_replaces_truncated_multibyte_sequence(self):
        raw = "あいうえお".encode("utf-8")[:-1]
        result = url_charset.decode_response_body(raw, content_type="text/html; charset=utf-8")
        self.assertIn("あいうえ", result)

    # 空のボディが空文字列としてデコードされることを検証します。
    # Verify an empty body decodes to an empty string.
    def test_decodes_empty_body(self):
        self.assertEqual(url_charset.decode_response_body(b""), "")
