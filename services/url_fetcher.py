from __future__ import annotations

import ipaddress
import logging
import re
import socket
import threading
from contextlib import contextmanager
from html.parser import HTMLParser
from typing import Iterator
from urllib.parse import urljoin, urlparse

import requests
import urllib3.util.connection as _urllib3_conn

logger = logging.getLogger(__name__)

MAX_URLS_PER_MESSAGE = 3
MAX_URL_RESPONSE_BYTES = 300_000   # 300 KB raw cap before decoding
MAX_URL_TEXT_CHARS = 30_000        # chars of plain text kept per URL
URL_FETCH_TIMEOUT = 10             # seconds
MAX_REDIRECT_HOPS = 5

_URL_RE = re.compile(r"https?://[^\s<>\"'`()\[\]{}|\\^]+", re.IGNORECASE)

# SSRF protection: block requests to loopback, private, and link-local ranges.
_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("100.64.0.0/10"),    # carrier-grade NAT
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)
_BLOCKED_HOSTNAMES = frozenset({"localhost"})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})

_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ChatBot/1.0)",
    "Accept": "text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "ja,en;q=0.9",
}


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
    host, port = address[0], address[1]
    mapping: dict[str, str] | None = getattr(_dns_pin_local, "mapping", None)
    if mapping and host in mapping:
        address = (mapping[host], port)
    return _original_urllib3_create_connection(address, *args, **kwargs)


_urllib3_conn.create_connection = _pinned_create_connection


@contextmanager
def _pin_dns(host_to_ip: dict[str, str]) -> Iterator[None]:
    previous = getattr(_dns_pin_local, "mapping", None)
    _dns_pin_local.mapping = dict(host_to_ip)
    try:
        yield
    finally:
        _dns_pin_local.mapping = previous


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


def _resolve_safe_ip(url: str) -> str | None:
    """Return the resolved IP for *url* if it is safe to fetch, else None.

    Performs the SSRF check: rejects non-http(s) schemes, deny-listed
    hostnames, and IPs in private/loopback/link-local ranges. The returned
    IP is used to pin DNS resolution during the actual fetch so a rebinding
    attack cannot redirect the TCP connection to a different address.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        hostname = parsed.hostname
        if not hostname:
            return None
        if hostname in _BLOCKED_HOSTNAMES:
            return None
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
        if any(ip in net for net in _BLOCKED_NETWORKS):
            return None
        return ip_str
    except Exception:
        return None


def _is_safe_url(url: str) -> bool:
    """Return True when the URL is safe to fetch (not targeting private networks)."""
    return _resolve_safe_ip(url) is not None


def fetch_url_content(url: str) -> str | None:
    """Fetch a single URL and return its readable plain-text content.

    Redirects are followed manually (up to MAX_REDIRECT_HOPS) and every hop
    is re-validated against the SSRF deny list so an attacker-controlled
    server cannot 302 us into the metadata service. DNS resolution is
    pinned to the IP we validated at SSRF-check time so a rebinding flip
    between check and connect cannot reach an internal address.
    """
    current_url = url
    host_to_ip: dict[str, str] = {}

    for _hop in range(MAX_REDIRECT_HOPS + 1):
        ip = _resolve_safe_ip(current_url)
        if ip is None:
            return None
        hostname = urlparse(current_url).hostname
        if hostname is None:
            return None
        host_to_ip[hostname] = ip

        try:
            with _pin_dns(host_to_ip):
                response = requests.get(
                    current_url,
                    headers=_FETCH_HEADERS,
                    timeout=URL_FETCH_TIMEOUT,
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
                        current_url = urljoin(current_url, location)
                        continue

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
                            # LLM 文脈に入れる抜粋用途なので、巨大ページは先頭だけ読んで打ち切る。
                            # メモリ消費と応答待ち時間を URL 1 件ごとに固定上限へ収めるため。
                            break

                    raw = b"".join(chunks).decode(
                        response.apparent_encoding or "utf-8",
                        errors="replace",
                    )
                    text = _extract_text_from_html(raw) if is_html else raw
                    return text[:MAX_URL_TEXT_CHARS] or None
                finally:
                    response.close()
        except Exception:
            logger.debug("Failed to fetch URL %s", current_url, exc_info=True)
            return None

    return None


def fetch_urls_content(urls: list[str]) -> dict[str, str]:
    """Fetch content for each URL; return {url: text} for successful fetches only."""
    result: dict[str, str] = {}
    for url in urls:
        content = fetch_url_content(url)
        if content:
            result[url] = content
    return result
