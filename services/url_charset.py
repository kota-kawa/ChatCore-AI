from __future__ import annotations

import codecs
import re

# 取得済みのレスポンスボディ（bytes）を文字列へデコードするための文字コード解決モジュール。
# Charset resolution used to decode an already-downloaded response body (bytes) into text.
#
# requests の `Response.apparent_encoding` は内部で `Response.content` を参照するため、
# `stream=True` + `iter_content()` で読み切ったレスポンスに対して呼ぶと
# RuntimeError("The content for this response was already consumed") になる。
# そのため、ここでは受信済みの bytes だけを入力に文字コードを決定する。
# `Response.apparent_encoding` touches `Response.content`, which raises
# RuntimeError("The content for this response was already consumed") once a
# `stream=True` response has been drained through `iter_content()`. This module
# therefore determines the charset from the received bytes alone.

# BOM は宣言より優先される（HTML 仕様の判定順に合わせる）。
# UTF-32 の BOM は UTF-16 の BOM を接頭辞に含むため、必ず先に判定する。
# A BOM outranks any declaration (matching the HTML spec's sniffing order).
# UTF-32 BOMs start with the UTF-16 BOMs, so they must be checked first.
_BOM_ENCODINGS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

# HTML の charset 宣言を探す範囲。仕様上も先頭 1024 バイト程度に置かれる想定。
# How far into the document to look for an HTML charset declaration.
_META_SNIFF_BYTES = 4096

# `<meta charset="euc-jp">` と `<meta http-equiv=... content="...; charset=euc-jp">` の
# どちらも `charset=` を含むため、1つのパターンで拾う。
# Both `<meta charset="euc-jp">` and the http-equiv form contain `charset=`,
# so a single pattern covers them.
_META_CHARSET_RE = re.compile(
    rb"<meta[^>]*?charset\s*=\s*[\"']?\s*([a-zA-Z0-9_\-.:]+)",
    re.IGNORECASE,
)
_HEADER_CHARSET_RE = re.compile(
    r"charset\s*=\s*[\"']?\s*([a-zA-Z0-9_\-.:]+)",
    re.IGNORECASE,
)

_FALLBACK_ENCODING = "utf-8"


# コーデック名として実在し使用できる場合のみ、正規化した名前を返す
# Return the normalized codec name only when it names a usable codec.
def _normalize_encoding(name: str | None) -> str | None:
    if not name:
        return None
    candidate = name.strip().strip("\"'").rstrip(";").strip()
    if not candidate:
        return None
    try:
        return codecs.lookup(candidate).name
    except (LookupError, ValueError):
        return None


# 先頭バイト列の BOM から文字コードを判定する
# Detect the charset from a leading byte-order mark.
def _charset_from_bom(raw: bytes) -> str | None:
    for bom, encoding in _BOM_ENCODINGS:
        if raw.startswith(bom):
            return encoding
    return None


# Content-Type ヘッダーの charset パラメータから文字コードを判定する
# Detect the charset from the Content-Type header's charset parameter.
def _charset_from_content_type(content_type: str) -> str | None:
    if not content_type:
        return None
    match = _HEADER_CHARSET_RE.search(content_type)
    return _normalize_encoding(match.group(1) if match else None)


# HTML 内の meta 宣言から文字コードを判定する
# Detect the charset from an in-document HTML meta declaration.
def _charset_from_html_meta(raw: bytes) -> str | None:
    match = _META_CHARSET_RE.search(raw[:_META_SNIFF_BYTES])
    if not match:
        return None
    return _normalize_encoding(match.group(1).decode("ascii", errors="ignore"))


# 宣言が無いバイト列が厳密に UTF-8 として解釈できるかを判定する
# Check whether undeclared bytes decode strictly as UTF-8.
#
# 現在の Web は UTF-8 が支配的な一方、統計的推定は ASCII 主体の本文を cp1252 や
# shift_jis と誤判定しがちなので、厳密デコードが通るなら推定より優先する。
# UTF-8 dominates the modern web, while statistical detection often mislabels
# mostly-ASCII bodies as cp1252 or shift_jis, so a clean strict decode wins.
def _charset_from_strict_utf8(raw: bytes) -> str | None:
    if not raw:
        return None
    # サイズ上限による末尾の途中切断だけは許容する（UTF-8 の最大長は4バイト）。
    # Tolerate only a trailing sequence cut short by the size cap (UTF-8 is 4 bytes max).
    for trim in range(0, min(3, len(raw)) + 1):
        candidate = raw[: len(raw) - trim] if trim else raw
        try:
            candidate.decode("utf-8")
        except UnicodeDecodeError:
            continue
        return "utf-8"
    return None


# 宣言が無いバイト列から統計的に文字コードを推定する（charset-normalizer は requests の依存として同梱）
# Statistically detect the charset of undeclared bytes (charset-normalizer ships with requests).
def _charset_from_detection(raw: bytes) -> str | None:
    if not raw:
        return None
    try:
        from charset_normalizer import from_bytes
    except ImportError:
        return None
    try:
        best = from_bytes(raw).best()
    except Exception:
        return None
    return _normalize_encoding(best.encoding if best is not None else None)


# 受信済みボディの文字コードを、BOM → ヘッダー宣言 → meta 宣言 → UTF-8 厳密判定 → 推定 の順で解決する
# Resolve the body charset in order: BOM, header, meta, strict UTF-8, detection.
def resolve_charset(
    raw: bytes,
    *,
    content_type: str = "",
    is_html: bool = False,
) -> str:
    resolvers = [
        lambda: _charset_from_bom(raw),
        lambda: _charset_from_content_type(content_type),
    ]
    if is_html:
        resolvers.append(lambda: _charset_from_html_meta(raw))
    resolvers.append(lambda: _charset_from_strict_utf8(raw))
    resolvers.append(lambda: _charset_from_detection(raw))

    for resolve in resolvers:
        encoding = resolve()
        if encoding:
            return encoding
    return _FALLBACK_ENCODING


# 受信済みボディを文字列へデコードする
# Decode an already-downloaded response body into text.
#
# サイズ上限で末尾を打ち切っている場合、マルチバイト文字が途中で切れることがある。
# 抜粋用途なので例外にせず、置換文字へ落として読める分だけを返す。
# The body may be truncated mid-multibyte-character by the size cap. This is an
# excerpt, so decoding never raises: undecodable bytes become replacement chars.
def decode_response_body(
    raw: bytes,
    *,
    content_type: str = "",
    is_html: bool = False,
) -> str:
    encoding = resolve_charset(raw, content_type=content_type, is_html=is_html)
    return raw.decode(encoding, errors="replace")
