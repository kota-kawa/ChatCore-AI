from __future__ import annotations

from typing import Any, List
from urllib.parse import urlencode, urlsplit

from fastapi import Request
from starlette.responses import RedirectResponse

from .web_constants import FRONTEND_URL


# 日本語: build frontend url の組み立て処理を担当します。
# English: Handle building for build frontend url.
def build_frontend_url(base_url: str, path: str = "", *, query: str | None = None) -> str:
    # フロントエンドURLを安全に連結して返す
    # Build an absolute frontend URL with normalized path/query.
    normalized_base = base_url.rstrip("/")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if path:
        normalized = path if path.startswith("/") else f"/{path}"
        url = f"{normalized_base}{normalized}"
    else:
        url = f"{normalized_base}/"
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if query:
        return f"{url}?{query}"
    return url


# 日本語: url for に関する処理の入口です。
# English: Entry point for logic related to url for.
def url_for(request: Request, endpoint: str, **values: Any) -> str:
    # FastAPI の URL 生成に query/path パラメータ分離を加え、Flask互換呼び出しを吸収する
    # Extend FastAPI URL building with path/query split for Flask-style compatibility.
    external = values.pop("_external", False)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if "filename" in values and "path" not in values:
        values["path"] = values.pop("filename")

    path_param_names: List[str] = []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for route in request.app.router.routes:
        if getattr(route, "name", None) == endpoint:
            path_param_names = list(getattr(route, "param_convertors", {}).keys())
            break

    path_params = {}
    for key in list(values.keys()):
        if key in path_param_names:
            path_params[key] = values.pop(key)

    url = request.url_for(endpoint, **path_params)
    if values:
        url = url.include_query_params(**values)

    if external:
        return str(url)

    if url.query:
        return f"{url.path}?{url.query}"
    return url.path


# 日本語: frontend url に関する処理の入口です。
# English: Entry point for logic related to frontend url.
def frontend_url(path: str = "", *, query: str | None = None) -> str:
    # フロントエンドURLを安全に連結して返す
    # Build an absolute frontend URL with normalized path/query.
    return build_frontend_url(FRONTEND_URL, path, query=query)


# 日本語: sanitize next path に関する処理の入口です。
# English: Entry point for logic related to sanitize next path.
def sanitize_next_path(next_path: Any, default: str = "/") -> str:
    # `next` は同一サイト内の相対パスのみ許可し、外部URLは拒否する
    # Allow only same-site relative paths for `next`; reject external URLs.
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not isinstance(next_path, str):
        return default

    candidate = next_path.strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not candidate.startswith("/"):
        return default

    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return default

    return candidate


# 日本語: redirect to frontend に関する処理の入口です。
# English: Entry point for logic related to redirect to frontend.
def redirect_to_frontend(
    request: Request, path: str | None = None, *, status_code: int = 302
) -> RedirectResponse:
    # 現在パス（または指定パス）をFRONTEND_URLへリダイレクトする
    # Redirect current (or provided) path to FRONTEND_URL.
    target_path = path if path is not None else request.url.path
    query = request.url.query or None
    return RedirectResponse(frontend_url(target_path, query=query), status_code=status_code)


# 日本語: frontend login url に関する処理の入口です。
# English: Entry point for logic related to frontend login url.
def frontend_login_url(next_path: str | None = None) -> str:
    # ログイン後遷移先を next クエリに埋め込んだログインURLを組み立てる
    # Build login URL with optional post-login `next` query parameter.
    safe_next_path = sanitize_next_path(next_path, default="/") if next_path else None
    query = urlencode({"next": safe_next_path}) if safe_next_path else None
    return frontend_url("/login", query=query)
