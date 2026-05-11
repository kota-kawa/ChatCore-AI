from __future__ import annotations

import ipaddress
import logging
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

MAX_URLS_PER_MESSAGE = 3
MAX_URL_RESPONSE_BYTES = 300_000   # 300 KB raw cap before decoding
MAX_URL_TEXT_CHARS = 30_000        # chars of plain text kept per URL
URL_FETCH_TIMEOUT = 10             # seconds

_URL_RE = re.compile(r"https?://[^\s<>\"'`()\[\]{}|\\^]+", re.IGNORECASE)

# SSRF protection: block requests to loopback, private, and link-local ranges.
_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("100.64.0.0/10"),    # carrier-grade NAT
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)
_BLOCKED_HOSTNAMES = frozenset({"localhost"})

_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ChatBot/1.0)",
    "Accept": "text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "ja,en;q=0.9",
}


class _TextExtractor(HTMLParser):
    """Lightweight HTML-to-text extractor using the stdlib html.parser."""

    _SKIP_TAGS = frozenset({
        "script", "style", "noscript", "nav", "footer",
        "head", "aside", "iframe", "svg", "canvas",
    })
    _BLOCK_TAGS = frozenset({
        "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "br", "tr", "article", "section", "blockquote",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _extract_text_from_html(raw_html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(raw_html)
    return extractor.get_text()


def extract_urls_from_text(text: str) -> list[str]:
    """Return up to MAX_URLS_PER_MESSAGE unique http/https URLs found in *text*."""
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


def _is_safe_url(url: str) -> bool:
    """Return True when the URL is safe to fetch (not targeting private networks).

    Resolves the hostname to an IP address before checking against blocked
    networks (SSRF protection). DNS rebinding is a known residual risk.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname in _BLOCKED_HOSTNAMES:
            return False
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
        return not any(ip in net for net in _BLOCKED_NETWORKS)
    except Exception:
        return False


def fetch_url_content(url: str) -> str | None:
    """Fetch a single URL and return its readable plain-text content.

    Returns None if the URL fails the SSRF safety check, the server returns
    a non-text content type, or any network or parsing error occurs.
    """
    if not _is_safe_url(url):
        return None
    try:
        with requests.get(
            url,
            headers=_FETCH_HEADERS,
            timeout=URL_FETCH_TIMEOUT,
            allow_redirects=True,
            stream=True,
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            is_html = "text/html" in content_type
            is_plain = "text/plain" in content_type
            if not (is_html or is_plain):
                return None

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=16_384):
                chunks.append(chunk)
                total += len(chunk)
                if total >= MAX_URL_RESPONSE_BYTES:
                    break

            raw = b"".join(chunks).decode(
                response.apparent_encoding or "utf-8",
                errors="replace",
            )

        text = _extract_text_from_html(raw) if is_html else raw
        return text[:MAX_URL_TEXT_CHARS] or None
    except Exception:
        logger.debug("Failed to fetch URL %s", url, exc_info=True)
        return None


def fetch_urls_content(urls: list[str]) -> dict[str, str]:
    """Fetch content for each URL; return {url: text} for successful fetches only."""
    result: dict[str, str] = {}
    for url in urls:
        content = fetch_url_content(url)
        if content:
            result[url] = content
    return result
