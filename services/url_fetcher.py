from __future__ import annotations

import ipaddress
import logging
import re
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

import requests
import urllib3.util.connection as _urllib3_conn

from services.url_charset import decode_response_body

# ロガーの設定
# Configure logger
logger = logging.getLogger(__name__)

# 定数定義
# Define constants
MAX_URLS_PER_MESSAGE = 3
MAX_URL_RESPONSE_BYTES = 300_000   # 300 KB raw cap before decoding
MAX_URL_TEXT_CHARS = 30_000        # chars of plain text kept per URL
URL_FETCH_TIMEOUT = 10             # seconds
URL_FETCH_TURN_BUDGET = 12         # seconds waiting for all pasted URLs
MAX_CONCURRENT_URL_FETCHES = 12
MAX_REDIRECT_HOPS = 5
MAX_LINKS_PER_DOCUMENT = 40
MAX_LINK_URL_CHARS = 1_000
MAX_LINK_TEXT_CHARS = 240
MAX_LINK_CONTEXT_CHARS = 320
MAX_IMAGES_PER_DOCUMENT = 20

# URL抽出用の正規表現
# Regular expression to extract URLs
_URL_RE = re.compile(r"https?://[^\s<>\"'`()\[\]{}|\\^]+", re.IGNORECASE)

_BLOCKED_HOSTNAMES = frozenset({"localhost"})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_fetch_slots = threading.BoundedSemaphore(MAX_CONCURRENT_URL_FETCHES)
_fetch_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_URL_FETCHES, thread_name_prefix="url-fetch")

# リクエストヘッダー
# Request headers
_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ChatBot/1.0)",
    "Accept": "text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "ja,en;q=0.9",
}


@dataclass(frozen=True)
class FetchedLink:
    """A normalized link discovered in a fetched HTML document."""

    url: str
    text: str
    context: str = ""


@dataclass(frozen=True)
class FetchedImage:
    """A normalized image candidate discovered in a fetched HTML document."""

    url: str
    alt: str = ""
    title: str = ""
    kind: str = "image"


@dataclass(frozen=True)
class FetchedUrlDocument:
    """Readable content and safe follow-up candidates from one URL fetch."""

    requested_url: str
    final_url: str
    title: str
    text: str
    links: tuple[FetchedLink, ...] = ()
    images: tuple[FetchedImage, ...] = ()


# --- DNS pinning to defeat DNS-rebinding-style SSRF -------------------------
# urllib3's create_connection is wrapped so that, while a fetch is in
# progress, any hostname we already validated is forced to resolve to the IP
# we validated. Without this, urllib3 would call getaddrinfo again at TCP
# connect time and could be steered to a freshly-flipped DNS response that
# now points at an internal address. The pin is thread-local so concurrent
# fetches don't interfere, and HTTPS continues to validate against the
# original hostname because SNI/cert verification runs after the TCP layer.
_dns_pin_local = threading.local()
_original_urllib3_create_connection = _urllib3_conn.create_connection


def _pinned_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
    # 検証済みホスト名に対するDNSピン留めを考慮したコネクション作成
    # Create connection respecting DNS pinning for verified hostnames
    host, port = address[0], address[1]
    mapping: dict[str, str] | None = getattr(_dns_pin_local, "mapping", None)
    if mapping and host in mapping:
        address = (mapping[host], port)
    return _original_urllib3_create_connection(address, *args, **kwargs)


_urllib3_conn.create_connection = _pinned_create_connection


@contextmanager
def _pin_dns(host_to_ip: dict[str, str]) -> Iterator[None]:
    # DNSピン留めを一時的に適用するコンテキストマネージャ
    # Context manager to temporarily apply DNS pinning
    previous = getattr(_dns_pin_local, "mapping", None)
    _dns_pin_local.mapping = dict(host_to_ip)
    try:
        yield
    finally:
        _dns_pin_local.mapping = previous


def _new_direct_session() -> requests.Session:
    """Avoid proxy and .netrc settings that could bypass pinning or disclose local credentials."""
    session = requests.Session()
    session.trust_env = False
    return session


class _TextExtractor(HTMLParser):
    """stdlib html.parserを使用した軽量なHTMLからテキストへの抽出器。

    Lightweight HTML-to-text extractor using the stdlib html.parser.
    """

    _SKIP_TAGS = frozenset({
        "script", "style", "noscript", "nav", "footer",
        "head", "aside", "iframe", "svg", "canvas",
    })
    _BLOCK_TAGS = frozenset({
        "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "br", "tr", "article", "section", "blockquote",
    })

    def __init__(self) -> None:
        # 抽出器の初期化
        # Initialize the extractor
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._inside_title = False
        self._base_href = ""
        self._active_link: dict[str, object] | None = None
        self._raw_links: list[tuple[str, str, str]] = []
        self._raw_images: list[tuple[str, str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        # 無視対象のタグの開始時の処理
        # Handle the start of skip tags
        tag = tag.lower()
        attributes = {str(name).lower(): str(value or "") for name, value in attrs}
        if tag == "title":
            self._inside_title = True
        if tag == "base" and not self._base_href:
            self._base_href = attributes.get("href", "").strip()
        if tag == "meta":
            image_kind = self._meta_image_kind(attributes)
            content = attributes.get("content", "").strip()
            if image_kind and content:
                self._raw_images.append((content, "", "", image_kind))
        if tag == "link":
            rel = {item.strip().lower() for item in attributes.get("rel", "").split()}
            href = attributes.get("href", "").strip()
            if href and ("image_src" in rel or "image" in rel):
                self._raw_images.append((href, "", attributes.get("title", ""), "link"))
        if tag == "a" and self._skip_depth == 0:
            href = attributes.get("href", "").strip()
            if href:
                preceding_text = "".join(self._parts[-3:])[-MAX_LINK_CONTEXT_CHARS:]
                self._active_link = {
                    "href": href,
                    "title": attributes.get("title") or attributes.get("aria-label", ""),
                    "parts": [],
                    "context": preceding_text,
                }
        if tag == "img" and self._active_link is not None and self._skip_depth == 0:
            fallback_text = attributes.get("alt") or attributes.get("title", "")
            if fallback_text.strip():
                parts = self._active_link["parts"]
                assert isinstance(parts, list)
                parts.append(fallback_text)
        if tag == "img" and self._skip_depth == 0:
            image_url = (
                attributes.get("src")
                or attributes.get("data-src")
                or attributes.get("data-original")
                or self._first_srcset_url(attributes.get("srcset") or attributes.get("data-srcset", ""))
            ).strip()
            if image_url:
                self._raw_images.append(
                    (
                        image_url,
                        attributes.get("alt", ""),
                        attributes.get("title", ""),
                        "img",
                    )
                )
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    @staticmethod
    def _meta_image_kind(attributes: dict[str, str]) -> str:
        property_name = attributes.get("property", "").strip().lower()
        name = attributes.get("name", "").strip().lower()
        if property_name in {"og:image", "og:image:url"}:
            return "og:image"
        if name in {"twitter:image", "twitter:image:src"}:
            return "twitter:image"
        return ""

    @staticmethod
    def _first_srcset_url(srcset: str) -> str:
        for candidate in srcset.split(","):
            url = candidate.strip().split(None, 1)[0] if candidate.strip() else ""
            if url:
                return url
        return ""

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        # タグ終了時の処理。ブロック要素の場合は改行を挿入する
        # Handle the end of tags; insert newlines for block tags
        tag = tag.lower()
        if tag == "a":
            self._finish_active_link()
        if tag == "title":
            self._inside_title = False
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        # テキストデータをパーツに追加する処理（スキップ対象外の場合）
        # Add text data to parts if not inside skip tags
        if self._inside_title and data.strip():
            self._title_parts.append(data)
        if self._active_link is not None and self._skip_depth == 0 and data.strip():
            parts = self._active_link["parts"]
            assert isinstance(parts, list)
            parts.append(data)
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def _finish_active_link(self) -> None:
        if self._active_link is None:
            return
        parts = self._active_link["parts"]
        assert isinstance(parts, list)
        text = " ".join("".join(parts).split())
        title = " ".join(str(self._active_link["title"]).split())
        context = " ".join(str(self._active_link["context"]).split())
        self._raw_links.append(
            (
                str(self._active_link["href"]),
                text or title,
                context,
            )
        )
        self._active_link = None

    def get_text(self) -> str:
        # 抽出されたテキストを結合して余分な空白や改行をクリーンアップする
        # Combine extracted text and clean up redundant spaces or newlines
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()

    def get_title(self) -> str:
        return " ".join("".join(self._title_parts).split())[:MAX_LINK_TEXT_CHARS]

    def get_raw_links(self) -> list[tuple[str, str, str]]:
        self._finish_active_link()
        return list(self._raw_links)

    def get_base_href(self) -> str:
        return self._base_href

    def get_raw_images(self) -> list[tuple[str, str, str, str]]:
        return list(self._raw_images)


def canonicalize_url(url: str) -> str | None:
    """Return a fragment-free canonical HTTP(S) URL, or ``None`` if invalid."""
    try:
        parsed = urlsplit(str(url or "").strip())
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        hostname = parsed.hostname.lower()
        if ":" not in hostname:
            # Requests converts IDNs to ASCII before connecting; pinning must use that same host.
            hostname = hostname.encode("idna").decode("ascii")
        display_hostname = f"[{hostname}]" if ":" in hostname else hostname
        port = parsed.port
        # The fetcher also handles discovered links and redirects; one check protects every path.
        if port is not None and port != (80 if scheme == "http" else 443):
            return None
        netloc = display_hostname
        normalized = urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))
        return normalized if len(normalized) <= MAX_LINK_URL_CHARS else None
    except (TypeError, ValueError):
        return None


def _extract_document_from_html(
    raw_html: str,
    *,
    requested_url: str,
    final_url: str,
) -> FetchedUrlDocument:
    extractor = _TextExtractor()
    extractor.feed(raw_html)
    normalized_final_url = canonicalize_url(final_url)
    if normalized_final_url is None:
        raise ValueError("Fetched document has an invalid final URL.")
    link_base_url = (
        canonicalize_url(urljoin(normalized_final_url, extractor.get_base_href()))
        if extractor.get_base_href()
        else normalized_final_url
    ) or normalized_final_url
    seen: set[str] = {normalized_final_url}
    links: list[FetchedLink] = []
    for href, text, context in extractor.get_raw_links():
        normalized_url = canonicalize_url(urljoin(link_base_url, href))
        if normalized_url is None or normalized_url in seen:
            continue
        seen.add(normalized_url)
        normalized_text = " ".join(text.split())[:MAX_LINK_TEXT_CHARS]
        if not normalized_text:
            continue
        links.append(
            FetchedLink(
                url=normalized_url,
                text=normalized_text,
                context=" ".join(context.split())[-MAX_LINK_CONTEXT_CHARS:],
            )
        )
        if len(links) >= MAX_LINKS_PER_DOCUMENT:
            break
    images: list[FetchedImage] = []
    seen_image_urls: set[str] = set()
    for raw_url, alt, title, kind in extractor.get_raw_images():
        normalized_url = canonicalize_url(urljoin(link_base_url, raw_url))
        if normalized_url is None or normalized_url in seen_image_urls:
            continue
        seen_image_urls.add(normalized_url)
        images.append(
            FetchedImage(
                url=normalized_url,
                alt=" ".join(alt.split())[:MAX_LINK_TEXT_CHARS],
                title=" ".join(title.split())[:MAX_LINK_TEXT_CHARS],
                kind=kind,
            )
        )
        if len(images) >= MAX_IMAGES_PER_DOCUMENT:
            break
    return FetchedUrlDocument(
        requested_url=requested_url,
        final_url=normalized_final_url,
        title=extractor.get_title(),
        text=extractor.get_text()[:MAX_URL_TEXT_CHARS],
        links=tuple(links),
        images=tuple(images),
    )


def extract_urls_from_text(text: str) -> list[str]:
    """テキスト内から最大 MAX_URLS_PER_MESSAGE 件のユニークな http/https URL を返す。

    Return up to MAX_URLS_PER_MESSAGE unique http/https URLs found in *text*.
    """
    seen: set[str] = set()
    result: list[str] = []
    for raw_url in _URL_RE.findall(text):
        url = raw_url.rstrip(".,;:!?)")
        if url not in seen:
            seen.add(url)
            result.append(url)
        if len(result) >= MAX_URLS_PER_MESSAGE:
            break
    return result


def url_for_logging(url: str) -> str:
    """Keep only the URL origin and path in diagnostics, never credentials or signed parameters."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if not hostname or parsed.scheme.lower() not in {"http", "https"}:
            return "<invalid URL>"
        display_hostname = f"[{hostname}]" if ":" in hostname else hostname
        port = parsed.port
        netloc = f"{display_hostname}:{port}" if port is not None else display_hostname
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, "", ""))
    except (TypeError, ValueError):
        return "<invalid URL>"


def _resolve_safe_ip(url: str) -> str | None:
    """URLが安全に取得可能であれば解決されたIPを返し、そうでなければ None を返す。

    Return the resolved IP for *url* if it is safe to fetch, else None.

    Performs the SSRF check: rejects non-http(s) schemes, blocked
    hostnames, and any DNS answer that is not a global IP. The returned
    IP is used to pin DNS resolution during the actual fetch so a rebinding
    attack cannot redirect the TCP connection to a different address.
    """
    try:
        normalized_url = canonicalize_url(url)
        if normalized_url is None:
            return None
        parsed = urlparse(normalized_url)
        hostname = parsed.hostname
        if not hostname:
            return None
        if hostname in _BLOCKED_HOSTNAMES:
            return None
        answers = socket.getaddrinfo(hostname, parsed.port or (80 if parsed.scheme == "http" else 443), type=socket.SOCK_STREAM)
        if not answers:
            return None
        safe_ips: list[str] = []
        for family, _type, _proto, _canonname, sockaddr in answers:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                return None
            ip = ipaddress.ip_address(sockaddr[0])
            # A mixed public/private DNS set must fail closed even though one address could be pinned.
            if (
                not ip.is_global
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
                or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped and not ip.ipv4_mapped.is_global)
            ):
                return None
            safe_ips.append(str(ip))
    except Exception:
        # Exception messages can include the original signed URL; never log their contents.
        logger.debug("Failed to resolve a safe IP for URL %s; treating it as unsafe.", url_for_logging(url))
        return None
    else:
        return safe_ips[0]


def _fetch_url_document_impl(url: str) -> FetchedUrlDocument | None:
    """単一のURLを取得し、本文・最終URL・追跡可能リンクを返す。

    Fetch a single URL and return readable content plus discovered links.

    Redirects are followed manually (up to MAX_REDIRECT_HOPS) and every hop
    is re-validated against the global-IP requirement so an attacker-controlled
    server cannot 302 us into the metadata service. DNS resolution is
    pinned to the IP we validated at SSRF-check time so a rebinding flip
    between check and connect cannot reach an internal address.
    """
    current_url = url
    host_to_ip: dict[str, str] = {}
    deadline = time.monotonic() + URL_FETCH_TIMEOUT

    for _hop in range(MAX_REDIRECT_HOPS + 1):
        if time.monotonic() >= deadline:
            return None
        normalized_current_url = canonicalize_url(current_url)
        if normalized_current_url is None:
            return None
        current_url = normalized_current_url
        ip = _resolve_safe_ip(current_url)
        if ip is None:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        hostname = urlparse(current_url).hostname
        if hostname is None:
            return None
        host_to_ip[hostname] = ip

        try:
            with _new_direct_session() as session, _pin_dns(host_to_ip):
                response = session.get(
                    current_url,
                    headers=_FETCH_HEADERS,
                    timeout=remaining,
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    if response.status_code in _REDIRECT_STATUS_CODES:
                        location = response.headers.get("Location")
                        if not location:
                            return None
                        # リダイレクト先も次ループで再度 SSRF 検査する。
                        # requests の自動リダイレクトを使わないのは、各 hop の検査と DNS pinning を挟むため。
                        # Redirects are manually validated and resolved in the next iteration.
                        current_url = urljoin(current_url, location)
                        continue

                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    media_type = content_type.split(";", 1)[0].strip()
                    is_html = media_type == "text/html"
                    is_plain = media_type == "text/plain"
                    if not (is_html or is_plain):
                        return None

                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_content(chunk_size=16_384):
                        if time.monotonic() >= deadline:
                            return None
                        remaining_bytes = MAX_URL_RESPONSE_BYTES - total
                        chunks.append(chunk[:remaining_bytes])
                        total += min(len(chunk), remaining_bytes)
                        if total >= MAX_URL_RESPONSE_BYTES:
                            # LLM 文脈に入れる抜粋用途なので、巨大ページは先頭だけ読んで打ち切る。
                            # メモリ消費と応答待ち時間を URL 1 件ごとに固定上限へ収めるため。
                            # Truncate large pages to keep memory usage and latency bounded.
                            break

                    # ここで response.apparent_encoding は使えない。内部で
                    # response.content を参照するが、上の iter_content で
                    # ストリームを読み切っているため RuntimeError になる。
                    # 受信済みの bytes だけから文字コードを判定する。
                    # response.apparent_encoding cannot be used here: it reads
                    # response.content, which raises RuntimeError once the stream
                    # above has been drained. Resolve the charset from the bytes
                    # we already hold instead.
                    raw = decode_response_body(
                        b"".join(chunks),
                        content_type=content_type,
                        is_html=is_html,
                    )
                    if is_html:
                        document = _extract_document_from_html(
                            raw,
                            requested_url=url,
                            final_url=current_url,
                        )
                        return document if document.text else None
                    text = raw[:MAX_URL_TEXT_CHARS]
                    if not text:
                        return None
                    return FetchedUrlDocument(
                        requested_url=url,
                        final_url=current_url,
                        title="",
                        text=text,
                    )
                finally:
                    response.close()
        except Exception:
            logger.debug("Failed to fetch URL %s", url_for_logging(current_url))
            return None

    return None


def fetch_url_document(url: str) -> FetchedUrlDocument | None:
    """Return within one URL's waiting limit while bounding unfinished network workers globally."""
    if not _fetch_slots.acquire(blocking=False):
        return None
    try:
        future = _fetch_executor.submit(_fetch_url_document_impl, url)
    except Exception:
        _fetch_slots.release()
        return None
    # A timed-out DNS or read can continue; retain its slot until the worker actually exits.
    future.add_done_callback(lambda _future: _fetch_slots.release())
    try:
        return future.result(timeout=URL_FETCH_TIMEOUT)
    except FuturesTimeoutError:
        future.cancel()
        return None
    except Exception:
        logger.debug("Failed to fetch URL %s", url_for_logging(url))
        return None


def fetch_url_content(url: str) -> str | None:
    """単一URLの本文だけを返す、既存呼び出し向けの互換ラッパー。

    Compatibility wrapper returning only the readable text for one URL.
    """
    document = fetch_url_document(url)
    return document.text if document is not None else None


def fetch_urls_documents(urls: list[str]) -> dict[str, FetchedUrlDocument]:
    """各URLの文書を取得し、本文を得られたものだけを {url: document} で返す。

    Fetch each URL and return {url: document} for the fetches that yielded text.
    """
    if not urls:
        return {}
    unique_urls = list(dict.fromkeys(urls))[:MAX_URLS_PER_MESSAGE]
    result: dict[str, FetchedUrlDocument] = {}
    executor = ThreadPoolExecutor(max_workers=len(unique_urls), thread_name_prefix="chat-url-fetch")
    try:
        future_to_url = {executor.submit(fetch_url_document, url): url for url in unique_urls}
        try:
            # Concurrent starts make the per-URL limit tighter today; the turn limit stays an independent ceiling.
            for future in as_completed(future_to_url, timeout=min(URL_FETCH_TIMEOUT, URL_FETCH_TURN_BUDGET)):
                url = future_to_url[future]
                try:
                    document = future.result()
                except Exception:
                    logger.debug("Failed to collect fetched URL %s", url_for_logging(url))
                    continue
                if document is not None and document.text:
                    result[url] = document
        except FuturesTimeoutError:
            pass
    finally:
        # A stalled resolver or read must not hold the chat turn after its waiting budget.
        executor.shutdown(wait=False, cancel_futures=True)
    return {url: result[url] for url in unique_urls if url in result}


def fetch_urls_content(urls: list[str]) -> dict[str, str]:
    """各URLの内容を取得し、成功した結果のみを {url: text} の形式で返す。

    Fetch content for each URL; return {url: text} for successful fetches only.
    """
    return {url: document.text for url, document in fetch_urls_documents(urls).items()}
