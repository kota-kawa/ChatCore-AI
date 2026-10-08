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

import base64
import binascii
import hashlib
import hmac
import re

from services.runtime_config import get_session_secret_key

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
