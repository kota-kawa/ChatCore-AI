"""生成UIの中で使う Web 検索画像を、自オリジンから中継するための署名付きパス。

Signed same-origin paths that relay web-search images into a generated UI.

生成UIのサンドボックスは外部ホストを全て遮断している。画像の読み込み先を外へ開けると、
LLM が書いた JavaScript が画像URLのクエリに会話内容を載せて送れてしまうため、開けるのは
このパスだけにする。サンドボックスは不透明オリジンで Cookie を送らないので、セッションでは
なく署名で守る。署名はサーバーが検索結果から選んだ画像URLにしか付けないため、生成UI側は
任意のURLを取得させられない。

The generated-UI sandbox blocks every external host. Opening image loads to the outside would
let model-written JavaScript ship conversation content in an image URL's query string, so this
path is the only thing opened. The sandbox runs on an opaque origin and sends no cookie, so the
path is guarded by a signature rather than the session. Only image URLs the server selected
from search results are ever signed, so a generated UI cannot make the server fetch an
arbitrary URL.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import re
import time
from collections import OrderedDict

from services.async_utils import run_blocking
from services.runtime_config import get_session_secret_key
from services.url_fetcher import FetchedImageContent, FetchSlotsBusyError, fetch_image_content

WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX = "/api/chat/web-images/"

_SIGNATURE_LENGTH = 32
_SIGNATURE_RE = re.compile(rf"[0-9a-f]{{{_SIGNATURE_LENGTH}}}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{1,4000}")
_PROXY_PATH_RE = re.compile(
    rf"{re.escape(WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX)}(?P<signature>[0-9a-f]{{{_SIGNATURE_LENGTH}}})/(?P<token>[A-Za-z0-9_-]{{1,4000}})"
)
# 同じ秘密鍵を使う他の署名と衝突させないための用途ラベル。
# Purpose label that keeps this signature apart from others derived from the same key.
_SIGNING_CONTEXT = b"web-search-image-proxy:v1:"
# 秘密鍵が無い開発環境でもパスの形は保つ。本番は app.py が FASTAPI_SECRET_KEY を必須にしている。
# Keeps the path shape in development without a key; app.py requires FASTAPI_SECRET_KEY in production.
_DEVELOPMENT_SIGNING_SECRET = "web-search-image-proxy-development-secret"


# 取得結果を持つ時間。この間は、ブラウザが同じパスを何度開いても元サイトへは取りに行かない。
# 生成された JavaScript が取得の回数や間隔で元サイトへ情報を送る経路を塞ぐためで、失敗も覚える。
# How long a fetch outcome is kept. Within it, no number of requests for the same path reaches the
# origin again, which closes the channel where generated JavaScript signals the origin through
# how often or when it loads an image. Failures are remembered too.
IMAGE_CACHE_TTL_SECONDS = 86_400
IMAGE_FAILURE_TTL_SECONDS = 600
MAX_IMAGE_CACHE_BYTES = 32_000_000
MAX_IMAGE_CACHE_ENTRIES = 512

# 保持と取得中の一覧はイベントループのスレッドだけが触る。待ち合わせをスレッドではなく
# タスクで行うのは、同じ画像への要求が重なってもブロッキング用のスレッドを占有しないため。
# The cache and the in-flight map are touched only on the event-loop thread. Waiting is done with
# tasks rather than threads so overlapping requests for one image never hold blocking workers.
_image_cache: OrderedDict[str, tuple[float, FetchedImageContent | None]] = OrderedDict()
_image_cache_bytes = 0
_inflight_fetches: dict[str, asyncio.Future[FetchedImageContent | None]] = {}


def _cached_image(image_url: str) -> tuple[bool, FetchedImageContent | None]:
    entry = _image_cache.get(image_url)
    if entry is None:
        return False, None
    expires_at, image = entry
    if expires_at <= time.monotonic():
        _drop_cached_image(image_url)
        return False, None
    _image_cache.move_to_end(image_url)
    return True, image


def _drop_cached_image(image_url: str) -> None:
    global _image_cache_bytes
    _, image = _image_cache.pop(image_url)
    if image is not None:
        _image_cache_bytes -= len(image.data)


def _store_image(image_url: str, image: FetchedImageContent | None) -> None:
    global _image_cache_bytes
    if image_url in _image_cache:
        _drop_cached_image(image_url)
    ttl = IMAGE_CACHE_TTL_SECONDS if image is not None else IMAGE_FAILURE_TTL_SECONDS
    _image_cache[image_url] = (time.monotonic() + ttl, image)
    if image is not None:
        _image_cache_bytes += len(image.data)
    while len(_image_cache) > 1 and (
        _image_cache_bytes > MAX_IMAGE_CACHE_BYTES or len(_image_cache) > MAX_IMAGE_CACHE_ENTRIES
    ):
        _drop_cached_image(next(iter(_image_cache)))


async def _fetch_and_store_image(image_url: str) -> FetchedImageContent | None:
    try:
        image = await run_blocking(fetch_image_content, image_url)
    except FetchSlotsBusyError:
        # 混雑で取得しなかった場合は失敗として覚えない。元サイトへは何も送っていない。
        # A fetch skipped for load is not remembered as a failure; nothing reached the origin.
        return None
    _store_image(image_url, image)
    return image


async def load_web_search_image(image_url: str) -> FetchedImageContent | None:
    """Return the image for a signed URL, fetching the origin at most once per cache period."""
    cached, image = _cached_image(image_url)
    if cached:
        return image
    pending = _inflight_fetches.get(image_url)
    if pending is None:
        pending = asyncio.ensure_future(_fetch_and_store_image(image_url))
        _inflight_fetches[image_url] = pending
        pending.add_done_callback(lambda _done: _inflight_fetches.pop(image_url, None))
    # 要求の1つが切断されても、他の要求と共有している取得は止めない。
    # One disconnected request must not cancel the fetch the other requests share.
    return await asyncio.shield(pending)


def _signature(image_url: str) -> str:
    secret = get_session_secret_key() or _DEVELOPMENT_SIGNING_SECRET
    digest = hmac.new(
        secret.encode("utf-8"),
        _SIGNING_CONTEXT + image_url.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:_SIGNATURE_LENGTH]


def build_web_search_image_proxy_path(image_url: str) -> str:
    """Return the signed relay path for an image URL the server selected."""
    token = base64.urlsafe_b64encode(image_url.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX}{_signature(image_url)}/{token}"


def resolve_web_search_image_proxy_url(signature: str, token: str) -> str | None:
    """Return the original image URL when the signature matches it, else None."""
    if not _SIGNATURE_RE.fullmatch(signature or "") or not _TOKEN_RE.fullmatch(token or ""):
        return None
    try:
        image_url = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not hmac.compare_digest(signature, _signature(image_url)):
        return None
    return image_url


def is_signed_web_search_image_proxy_path(path: object) -> bool:
    """Whether *path* is a relay path carrying a signature this server issued."""
    if not isinstance(path, str):
        return False
    match = _PROXY_PATH_RE.fullmatch(path)
    if match is None:
        return False
    return resolve_web_search_image_proxy_url(match.group("signature"), match.group("token")) is not None
