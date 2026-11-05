"""認証モジュール共通の補助関数。

ログイン検証・Google OAuth 用のセッション掃除、サービス解決、ログイン後の後処理(既定タスクのコピー、ゲストのプロンプト引き継ぎ)、
Google 認証後のリダイレクト先 URL の組み立てをまとめる。auth_email / auth_google / auth_passkeys / auth_account から使われ、
依存は auth_support.dep() 経由で blueprints.auth から引く。

Helpers shared by the authentication modules: session cleanup for login verification and Google OAuth, service resolution,
post-login follow-ups (copying default tasks, claiming guest prompts) and redirect URL building after Google sign-in.
Used by auth_email / auth_google / auth_passkeys / auth_account; dependencies are resolved from blueprints.auth through auth_support.dep().
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Request

from blueprints.auth_support import call_dependency, dep


# メール認証コードによるログイン検証の途中状態を、セッションからすべて消す。
# Remove every in-progress email-code login verification value from the session.
def _clear_login_verification_session(session: dict[str, Any]) -> None:
    session.pop("login_verification_code", None)
    session.pop("login_temp_user_id", None)
    session.pop("login_temp_email", None)
    session.pop("login_verification_code_issued_at", None)
    session.pop("login_verification_code_attempts", None)
    session.pop("login_verification_locale", None)


# Google OAuth の途中状態(state・リダイレクト先・PKCE の code_verifier・ログイン後の遷移先)をセッションから消す。
# Remove all in-progress Google OAuth values (state, redirect URI, PKCE code verifier and post-login next path) from the session.
def _clear_google_oauth_session(session: dict[str, Any]) -> None:
    session.pop("google_oauth_state", None)
    session.pop("google_redirect_uri", None)
    session.pop(dep("GOOGLE_CODE_VERIFIER_SESSION_KEY"), None)
    session.pop(dep("GOOGLE_NEXT_PATH_SESSION_KEY"), None)


# Google OAuth の state・リダイレクト先・code_verifier だけを消す。遷移先(next)は残すので、失敗後のログイン画面へ引き継げる。
# Remove only the Google OAuth state, redirect URI and code verifier; the next path is kept so it can carry over to the login page after
# a failure.
def _clear_google_oauth_state(session: dict[str, Any]) -> None:
    session.pop("google_oauth_state", None)
    session.pop("google_redirect_uri", None)
    session.pop(dep("GOOGLE_CODE_VERIFIER_SESSION_KEY"), None)


# Google ログインが設定不足などで使えないときの 503 応答。
# 503 response for when Google login is unavailable, e.g. due to missing configuration.
def _google_login_unavailable_response() -> Any:
    return dep("jsonify")({"error": dep("GOOGLE_LOGIN_UNAVAILABLE_ERROR")}, status_code=503)


# Passkey 用ライブラリが使えないときの 503 応答。
# 503 response for when the Passkey library is unavailable.
def _passkey_unavailable_response() -> Any:
    return dep("jsonify")(
        {"status": "fail", "error": dep("PASSKEY_UNAVAILABLE_ERROR")},
        status_code=503,
    )


# 渡されたサービスが本物ならそれを使い、そうでなければリクエストから取得する(テストでは軽量な代替を渡せる)。
# Use the given service when it is a real AuthLimitService, otherwise fetch it from the request (tests may pass a light double).
def _resolve_auth_limit_service(request: Request, service: Any | None) -> Any:
    if isinstance(service, dep("AuthLimitService")):
        return service
    return dep("get_auth_limit_service")(request)


# 渡されたサービスが本物ならそれを使い、そうでなければリクエストから取得する(テストでは軽量な代替を渡せる)。
# Use the given service when it is a real LlmDailyLimitService, otherwise fetch it from the request (tests may pass a light double).
def _resolve_llm_daily_limit_service(request: Request, service: Any | None) -> Any:
    if isinstance(service, dep("LlmDailyLimitService")):
        return service
    return dep("get_llm_daily_limit_service")(request)


# セッションの user_id が整数のときだけ返す。それ以外は未ログイン扱いの None。
# Return the session user_id only when it is an int; otherwise None, treated as not signed in.
def _user_id_from_session(session: dict[str, Any]) -> int | None:
    user_id = session.get("user_id")
    if isinstance(user_id, int):
        return user_id
    return None


# ログイン成功後に既定タスクを利用者へコピーする。失敗してもログイン自体は成功させたいので、例外はログに残すだけにする。
# Copy the default tasks to the user after sign-in; failures are only logged so they never fail the login itself.
async def _copy_default_tasks_after_login(user_id: int, *, context: str) -> None:
    try:
        await call_dependency("copy_default_tasks_for_user", user_id)
    except Exception:
        dep("logger").exception(
            "%s: failed to copy default tasks for user %s",
            context,
            user_id,
        )


async def _claim_guest_prompts_after_login(
    request: Request,
    user_id: int,
    *,
    context: str,
) -> list[int]:
    """このブラウザのゲスト投稿プロンプトをログイン利用者へ引き継ぐ。失敗しても認証は失敗させない。

    Transfer this browser's guest prompts without making authentication fail.
    """
    guest_token = dep("get_guest_prompt_token")(request.session)
    if guest_token is None:
        return []

    try:
        return await call_dependency(
            "claim_guest_prompts_for_user",
            user_id,
            guest_token,
        )
    except Exception:
        dep("logger").exception(
            "%s: failed to claim guest prompts for user %s",
            context,
            user_id,
        )
        return []


# 基準 URL のスキームとホストに path をつないだ絶対 URL を作る。基準が相対 URL などで使えなければ None。
# Join a path onto the scheme and host of a reference URL; None when the reference is not an absolute URL.
def _build_absolute_url_from_reference(reference_url: str, path: str) -> str | None:
    parts = urlsplit(reference_url)
    if not parts.scheme or not parts.netloc:
        return None

    target_parts = urlsplit(path)
    normalized_path = target_parts.path if target_parts.path.startswith("/") else f"/{target_parts.path}"
    if not target_parts.path:
        normalized_path = "/"
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            normalized_path,
            target_parts.query,
            target_parts.fragment,
        )
    )


# 既存のクエリを保ったまま、同名のキーは上書きして URL にクエリを追加する。
# Add query parameters to a URL, keeping existing ones and overwriting any with the same key.
def _append_query_params(url: str, **params: str) -> str:
    parts = urlsplit(url)
    existing_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    existing_params.update(params)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(existing_params),
            parts.fragment,
        )
    )


# Google 認証後の戻り先 URL を作る。引数・セッション・設定・現在のリクエストの順に使える基準 URL を探し、無ければフロントエンドの URL に
# する。
# Build the post-Google-auth redirect URL from the first usable reference (argument, session, config, current request), else the
# frontend URL.
def _google_callback_redirect_target(
    request: Request,
    path: str,
    *,
    redirect_uri: str | None = None,
) -> str:
    session_redirect_uri = request.session.get("google_redirect_uri")
    configured_redirect_uri = (dep("os").getenv("GOOGLE_REDIRECT_URI") or "").strip()
    references: tuple[str | None, ...] = (
        redirect_uri,
        session_redirect_uri if isinstance(session_redirect_uri, str) else None,
        configured_redirect_uri or None,
        str(request.url),
    )
    for reference in references:
        if not isinstance(reference, str) or not reference:
            continue
        target = _build_absolute_url_from_reference(reference, path)
        if target:
            return target
    return dep("frontend_url")(path)


# ログイン開始時に保存した遷移先を、安全な内部パスに整えて返す。無ければ None。
# Return the next path saved at login start, sanitized to a safe internal path; None when absent.
def _google_next_path(session: dict[str, Any]) -> str | None:
    next_path = session.get(dep("GOOGLE_NEXT_PATH_SESSION_KEY"))
    if not isinstance(next_path, str) or not next_path:
        return None
    return dep("sanitize_next_path")(next_path, default="/")


# Google ログインの失敗時にログイン画面へ戻す。遷移先(next)があれば引き継ぎ、途中状態はセッションから消す。
# Send the user back to the login page after a Google login failure, carrying the next path when present and clearing the OAuth state.
def _redirect_to_login_after_google_failure(
    request: Request,
    session: dict[str, Any],
    *,
    redirect_uri: str | None = None,
    next_path: str | None = None,
    use_session_next: bool = True,
) -> Any:
    resolved_next_path = (
        _google_next_path(session)
        if use_session_next
        else (dep("sanitize_next_path")(next_path, default="/") if next_path else None)
    )
    target_url = _google_callback_redirect_target(
        request,
        "/login",
        redirect_uri=redirect_uri,
    )
    if resolved_next_path:
        target_url = _append_query_params(target_url, next=resolved_next_path)
    _clear_google_oauth_state(session)
    return dep("RedirectResponse")(target_url, status_code=302)
