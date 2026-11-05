"""Google OAuth ログイン(認可 URL への誘導とコールバック処理)。

開始時に state・PKCE の code_verifier・戻り先を短命のトランザクションとして保存し、Cookie には state だけを持たせる。
コールバックではそれを突き合わせて Google からトークンとプロフィールを取得し、既存ユーザーへの紐づけか新規作成のうえログインを確立する。
ルートへの結び付けは blueprints/auth.py、共通の補助関数は blueprints/auth_common.py にある。

Google OAuth login: redirect to the authorization URL and handle the callback.
At start, the state, PKCE code verifier and return URL are stored as a short-lived transaction and only the state goes in a cookie.
The callback matches them, fetches the token and profile from Google, links or creates the user and establishes the login.
Routes are bound in blueprints/auth.py; shared helpers are in blueprints/auth_common.py.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request

from blueprints.auth_common import (
    _append_query_params,
    _claim_guest_prompts_after_login,
    _clear_google_oauth_session,
    _clear_google_oauth_state,
    _copy_default_tasks_after_login,
    _google_callback_redirect_target,
    _google_login_unavailable_response,
    _google_next_path,
    _redirect_to_login_after_google_failure,
)
from blueprints.auth_support import call_dependency, dep


# 環境変数から Google OAuth のクライアント設定(client_id / client_secret など)を組み立てる。リダイレクト URI は呼び出し側で入れる。
# Build the Google OAuth client config from environment variables; the caller fills in the redirect URIs.
def _google_client_config() -> dict[str, Any]:
    return {
        "web": {
            "client_id": (dep("os").getenv("GOOGLE_CLIENT_ID") or "").strip(),
            "project_id": dep("os").getenv("GOOGLE_PROJECT_ID", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": (dep("os").getenv("GOOGLE_CLIENT_SECRET") or "").strip(),
            "redirect_uris": [],
            "javascript_origins": [dep("os").getenv("GOOGLE_JS_ORIGIN", "https://chatcore-ai.com")],
        }
    }


# クライアント設定に client_id と client_secret が揃っているか確認し、問題があればその説明を、無ければ None を返す。
# Check that client_id and client_secret are present; return a description of the problem, or None when valid.
def _validate_google_oauth_settings(client_config: dict[str, Any]) -> str | None:
    web_config = client_config.get("web") if isinstance(client_config, dict) else None
    if not isinstance(web_config, dict):
        return "Google OAuth client config is invalid."

    missing_keys: list[str] = []
    client_id = web_config.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        missing_keys.append("GOOGLE_CLIENT_ID")

    client_secret = web_config.get("client_secret")
    if not isinstance(client_secret, str) or not client_secret:
        missing_keys.append("GOOGLE_CLIENT_SECRET")

    if missing_keys:
        return f"Missing required Google OAuth environment variables: {', '.join(missing_keys)}"

    return None


# Google から戻ってきたリクエストを、設定済みの redirect_uri のホスト・パスに合わせた URL に直す(トークン交換に渡す
# authorization_response 用)。
# Rewrite the incoming callback URL onto the host and path of the configured redirect_uri, for the authorization_response passed to the
# token exchange.
def _build_google_authorization_response(request: Request, redirect_uri: str) -> str:
    redirect_parts = urlsplit(redirect_uri)
    if redirect_parts.scheme and redirect_parts.netloc:
        return urlunsplit(
            (
                redirect_parts.scheme,
                redirect_parts.netloc,
                redirect_parts.path,
                request.url.query,
                "",
            )
        )
    return str(request.url)


# リクエストのホストが設定済みの redirect_uri のホストと違うときだけ、正規のホストへの 302 を返す。同じ、または判断できないときは None。
# Return a 302 to the canonical host only when the request host differs from the configured redirect_uri host; None when it matches or
# cannot be judged.
def _build_google_login_host_redirect(request: Request, redirect_uri: str) -> Any | None:
    redirect_parts = urlsplit(redirect_uri)
    if not redirect_parts.scheme or not redirect_parts.netloc:
        return None

    request_host = request.headers.get("host") or request.url.netloc
    if not isinstance(request_host, str) or not request_host:
        return None

    if request_host.lower() == redirect_parts.netloc.lower():
        return None

    canonical_url = urlunsplit(
        (
            redirect_parts.scheme,
            redirect_parts.netloc,
            request.url.path,
            request.url.query,
            "",
        )
    )
    return dep("RedirectResponse")(canonical_url, status_code=302)


# アクセストークンで Google のユーザー情報 API からプロフィールを取得する。HTTP エラーや JSON でない応答は requests の例外にそろえて送出
# する。
# Fetch the profile from Google's userinfo API with the access token; HTTP errors and non-JSON bodies are raised as requests exceptions.
def _fetch_google_user_info(access_token: str) -> dict[str, Any]:
    response = dep("requests").get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as e:
        raise dep("requests").RequestException(f"Invalid JSON response: {e}") from e


# ユーザー情報の項目を前後の空白を除いた文字列で返す。無ければ空文字。
# Return a user-info field as a trimmed string, or an empty string when absent.
def _clean_google_field(user_info: dict[str, Any], key: str) -> str:
    value = user_info.get(key)
    if value is None:
        return ""
    return str(value).strip()


# OAuth の初期化・トークン交換で起こりうる例外の組をまとめる(except 節で一括して受けるため)。
# Group the exceptions that OAuth initialization and token exchange can raise, so one except clause can catch them.
def _oauth_error_classes() -> tuple[type[BaseException], ...]:
    return (
        dep("GoogleAuthError"),
        dep("OAuth2Error"),
        dep("requests").RequestException,
        ValueError,
    )


# OAuth トランザクション用の Cookie を削除する指示をレスポンスに付ける。
# Attach the instruction to delete the OAuth transaction cookie to the response.
def _clear_google_oauth_transaction_cookie(response: Any) -> Any:
    response.delete_cookie(
        dep("GOOGLE_OAUTH_TRANSACTION_COOKIE_NAME"),
        path="/",
    )
    return response


# Google ログインの失敗時の共通応答。ログイン画面へ戻し、OAuth の途中状態とトランザクション Cookie を片付ける。
# Common response for Google login failures: send the user back to the login page and clear the OAuth state and transaction cookie.
def _google_oauth_failure_response(
    request: Request,
    session: dict[str, Any],
    *,
    redirect_uri: str | None = None,
    next_path: str | None = None,
    dedicated_transaction: bool = False,
) -> Any:
    response = _redirect_to_login_after_google_failure(
        request,
        session,
        redirect_uri=redirect_uri,
        next_path=next_path,
        use_session_next=not dedicated_transaction,
    )
    _clear_google_oauth_session(session)
    return _clear_google_oauth_transaction_cookie(response)


# Google ログインの開始。認可 URL を作り、state と PKCE の code_verifier を短命トランザクションとして保存し、state を入れた Cookie を付
# けて Google へ 302 する。
# Start Google login: build the authorization URL, store the state and PKCE code verifier as a short-lived transaction, and 302 to
# Google with a state cookie.
async def google_login(request: Request):
    if dep("Flow") is None:
        dep("logger").error(
            "Google login is unavailable because google-auth-oauthlib is not installed."
        )
        return _google_login_unavailable_response()

    configured_redirect_uri = (dep("os").getenv("GOOGLE_REDIRECT_URI") or "").strip()
    redirect_uri = configured_redirect_uri or dep("url_for")(
        request,
        "auth.google_callback",
        _external=True,
    )

    canonical_redirect = _build_google_login_host_redirect(request, configured_redirect_uri)
    if canonical_redirect is not None:
        return canonical_redirect

    next_param = request.query_params.get("next")
    safe_next_path = dep("sanitize_next_path")(next_param, default="/") if next_param else None

    client_config = dep("_google_client_config")()
    settings_error = dep("_validate_google_oauth_settings")(client_config)
    if settings_error:
        dep("logger").error(
            "Google login is unavailable due to configuration error: %s",
            settings_error,
        )
        return _google_login_unavailable_response()

    client_config["web"]["redirect_uris"] = [redirect_uri]
    try:
        flow = dep("Flow").from_client_config(
            client_config,
            scopes=dep("GOOGLE_SCOPES"),
            redirect_uri=redirect_uri,
            autogenerate_code_verifier=True,
        )
        authorization_url, state = flow.authorization_url(prompt="consent")
    except _oauth_error_classes():
        dep("logger").exception("Failed to initialize Google OAuth authorization URL.")
        return _google_login_unavailable_response()

    code_verifier = getattr(flow, "code_verifier", None)
    if not isinstance(code_verifier, str) or not code_verifier:
        dep("logger").error("Google OAuth login initialization did not produce a PKCE code verifier.")
        return _google_login_unavailable_response()

    if not isinstance(state, str) or not state:
        dep("logger").error("Google OAuth login initialization did not produce a state value.")
        return _google_login_unavailable_response()

    stored = await dep("run_blocking")(
        dep("store_google_oauth_transaction"),
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        next_path=safe_next_path,
    )
    if not stored:
        dep("logger").error(
            "Google OAuth login could not persist its short-lived transaction."
        )
        return _google_login_unavailable_response()

    # OAuth一時状態は一般セッションへ保存しない。古いフローの残骸だけを除去する。
    # Keep OAuth transient state out of the general session; remove legacy leftovers.
    _clear_google_oauth_session(request.session)

    dep("logger").info(
        "Google OAuth login started. State: %s, Redirect URI: %s",
        state[:16] + "..." if state else "None",
        redirect_uri,
    )
    response = dep("RedirectResponse")(authorization_url, status_code=302)
    is_production = bool(dep("is_production_env")())
    response.set_cookie(
        dep("GOOGLE_OAUTH_TRANSACTION_COOKIE_NAME"),
        state,
        max_age=dep("GOOGLE_OAUTH_TRANSACTION_TTL_SECONDS"),
        path="/",
        httponly=True,
        secure=is_production,
        samesite="none" if is_production else "lax",
    )
    return response


# Google からのコールバック処理。state の突き合わせ → トークン交換 → プロフィール取得 → ユーザーの紐づけ/作成 → ログイン確立の順に進み、
# どこで失敗してもログイン画面へ戻す。
# Handle Google's callback: match state, exchange the token, fetch the profile, link or create the user and establish the login; any
# failure returns to the login page.
async def google_callback(request: Request):
    session = request.session
    transaction_cookie = request.cookies.get(dep("GOOGLE_OAUTH_TRANSACTION_COOKIE_NAME"))
    dedicated_transaction = transaction_cookie is not None

    if dep("Flow") is None:
        return _google_oauth_failure_response(
            request,
            session,
            dedicated_transaction=dedicated_transaction,
        )

    google_error = request.query_params.get("error")
    if google_error:
        dep("logger").warning(
            "Google OAuth callback: authorization error from Google: %s",
            google_error,
        )
        return _google_oauth_failure_response(
            request,
            session,
            dedicated_transaction=dedicated_transaction,
        )

    callback_state = request.query_params.get("state")
    state: str | None = None
    code_verifier: str | None = None
    redirect_uri: str | None = None
    next_path: str | None = None

    # Cookie に state が入っていれば新方式(サーバー側トランザクション)。無ければ旧セッション方式で処理する。
    # A state cookie means the new server-side transaction; without it, fall back to the legacy session form.
    if dedicated_transaction:
        if (
            not isinstance(transaction_cookie, str)
            or not isinstance(callback_state, str)
            or not dep("constant_time_compare")(transaction_cookie, callback_state)
        ):
            dep("logger").warning(
                "Google OAuth callback rejected because the transaction cookie and state differ."
            )
            return _google_oauth_failure_response(
                request,
                session,
                dedicated_transaction=True,
            )

        transaction = await dep("run_blocking")(
            dep("consume_google_oauth_transaction"),
            callback_state,
        )
        if transaction is None:
            dep("logger").warning(
                "Google OAuth callback transaction was missing, expired, or already consumed."
            )
            return _google_oauth_failure_response(
                request,
                session,
                dedicated_transaction=True,
            )

        state = transaction.state
        code_verifier = transaction.code_verifier
        redirect_uri = transaction.redirect_uri
        raw_next_path = transaction.next_path
        next_path = (
            dep("sanitize_next_path")(raw_next_path, default="/")
            if raw_next_path
            else None
        )
        dep("logger").info("Google OAuth callback transaction consumed.")
    else:
        # デプロイ前に開始したフローだけ、旧セッション保存形式で完了できるようにする。
        # Keep a compatibility path for OAuth flows started before this deployment.
        state_value = session.get("google_oauth_state")
        state = state_value if isinstance(state_value, str) else None
        dep("logger").info(
            "Google OAuth callback received through the legacy session path. "
            "Has state: %s, Session keys: %s",
            bool(state),
            list(session.keys()),
        )

        if not state:
            dep("logger").warning(
                "Google OAuth callback: session state missing. "
                "Session keys: %s, Request host: %s",
                list(session.keys()),
                request.headers.get("host"),
            )
            return _google_oauth_failure_response(request, session)

        if (
            not isinstance(callback_state, str)
            or not dep("constant_time_compare")(state, callback_state)
        ):
            dep("logger").warning(
                "Google OAuth callback rejected because the callback state differs from the session state."
            )
            return _google_oauth_failure_response(request, session)

        code_verifier_value = session.get(dep("GOOGLE_CODE_VERIFIER_SESSION_KEY"))
        code_verifier = code_verifier_value if isinstance(code_verifier_value, str) else None
        if not code_verifier:
            dep("logger").warning(
                "Google OAuth callback: PKCE code verifier missing. Session ID: %s",
                request.scope.get("session_id", "unknown"),
            )
            return _google_oauth_failure_response(request, session)

        redirect_uri_value = session.get("google_redirect_uri") or dep("os").getenv(
            "GOOGLE_REDIRECT_URI"
        )
        redirect_uri = redirect_uri_value if isinstance(redirect_uri_value, str) else None
        if not redirect_uri:
            redirect_uri = dep("url_for")(request, "auth.google_callback", _external=True)

        next_path = _google_next_path(session)

    if not isinstance(state, str) or not state or not code_verifier or not redirect_uri:
        dep("logger").warning("Google OAuth callback transaction data was invalid.")
        return _google_oauth_failure_response(
            request,
            session,
            redirect_uri=redirect_uri,
            next_path=next_path,
            dedicated_transaction=dedicated_transaction,
        )

    # 以降の失敗はすべて、同じ引数でログイン画面へ戻す応答にそろえる。
    # From here on every failure returns to the login page with the same arguments.
    def failure_response() -> Any:
        return _google_oauth_failure_response(
            request,
            session,
            redirect_uri=redirect_uri,
            next_path=next_path,
            dedicated_transaction=dedicated_transaction,
        )

    client_config = dep("_google_client_config")()
    settings_error = dep("_validate_google_oauth_settings")(client_config)
    if settings_error:
        dep("logger").error(
            "Google OAuth callback aborted due to configuration error: %s",
            settings_error,
        )
        return failure_response()

    success_redirect_url = _google_callback_redirect_target(
        request,
        next_path or "/",
        redirect_uri=redirect_uri,
    )
    client_config["web"]["redirect_uris"] = [redirect_uri]

    try:
        flow = dep("Flow").from_client_config(
            client_config,
            scopes=dep("GOOGLE_SCOPES"),
            state=state,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            autogenerate_code_verifier=False,
        )
    except _oauth_error_classes():
        dep("logger").exception("Failed to initialize Google OAuth callback flow.")
        return failure_response()

    authorization_response = dep("_build_google_authorization_response")(request, redirect_uri)
    try:
        await dep("run_blocking")(flow.fetch_token, authorization_response=authorization_response)
    except _oauth_error_classes():
        dep("logger").exception("Google OAuth token exchange failed.")
        return failure_response()

    _clear_google_oauth_state(session)

    credentials = flow.credentials
    access_token = getattr(credentials, "token", "")
    if not isinstance(access_token, str) or not access_token:
        dep("logger").error("Google OAuth callback completed without an access token.")
        return failure_response()

    try:
        user_info = await dep("run_blocking")(dep("_fetch_google_user_info"), access_token)
    except dep("requests").RequestException:
        dep("logger").exception("Failed to fetch Google user info.")
        return failure_response()

    email = _clean_google_field(user_info, "email")
    google_user_id = _clean_google_field(user_info, "id") or _clean_google_field(user_info, "sub")
    display_name = _clean_google_field(user_info, "name")
    picture = _clean_google_field(user_info, "picture")
    verified_email = bool(user_info.get("verified_email") or user_info.get("email_verified"))

    if not email or not google_user_id or not verified_email:
        missing = []
        if not email:
            missing.append("email")
        if not google_user_id:
            missing.append("google_user_id (id/sub)")
        if not verified_email:
            missing.append("verified_email/email_verified")
        dep("logger").warning(
            "Google OAuth callback: required fields missing: %s",
            ", ".join(missing),
        )
        return failure_response()

    # ユーザーの特定: Google ID で見つかれば紐づけを更新し、無ければメールで既存ユーザーを探して紐づけ、どちらも無ければ新規作成する。
    # 別の Google ID が既に紐づいたメールは乗っ取りを避けるため失敗にする。
    # Resolve the user: by Google ID (refresh the link), else by email (link it), else create one.
    # An email already linked to a different Google ID fails, to avoid account takeover.
    try:
        user = await call_dependency("get_user_by_google_id", google_user_id)
        should_mark_verified = False
        if user:
            user_id = user["id"]
            await call_dependency("link_google_account", user_id, google_user_id, email)
            should_mark_verified = not user.get("is_verified")
        else:
            user = await call_dependency("get_user_by_email", email)
            if user:
                existing_google_user_id = (user.get("provider_user_id") or "").strip()
                if existing_google_user_id and existing_google_user_id != google_user_id:
                    dep("logger").warning(
                        "Google OAuth callback: conflicting google_user_id for email %s",
                        email,
                    )
                    return failure_response()
                user_id = user["id"]
                await call_dependency("link_google_account", user_id, google_user_id, email)
                should_mark_verified = not user.get("is_verified")
            else:
                user_id = await call_dependency(
                    "create_user",
                    email,
                    username=display_name or None,
                    avatar_url=picture or None,
                    auth_provider=dep("GOOGLE_AUTH_PROVIDER"),
                    provider_user_id=google_user_id,
                    provider_email=email,
                    is_verified=True,
                )
                if not user_id:
                    dep("logger").error(
                        "Google OAuth callback: user creation returned no id for email %s",
                        email,
                    )
                    return failure_response()
    except Exception:
        dep("logger").exception(
            "Google OAuth callback: unexpected error during user lookup/creation."
        )
        return failure_response()

    dep("establish_authenticated_session")(request, int(user_id), email)

    try:
        await call_dependency(
            "update_user_profile_from_google_if_unset",
            user_id,
            display_name or None,
            picture or None,
        )
    except Exception:
        dep("logger").exception("Google OAuth callback: failed to sync profile for user %s", user_id)

    if should_mark_verified:
        try:
            await call_dependency("set_user_verified", user_id)
        except Exception:
            dep("logger").exception("Google OAuth callback: failed to verify user %s", user_id)

    await _copy_default_tasks_after_login(user_id, context="Google OAuth callback")
    await _claim_guest_prompts_after_login(
        request,
        int(user_id),
        context="Google OAuth callback",
    )

    try:
        persisted_user = await call_dependency("get_user_by_id", user_id)
        if persisted_user:
            session["user_email"] = persisted_user["email"]
    except Exception:
        dep("logger").exception("Google OAuth callback: failed to refresh email for user %s", user_id)

    # 遷移先(next)が無いときだけ auth=success を付けて戻し、フロント側でログイン完了を判別できるようにする。
    # Only when there is no next path, append auth=success so the frontend can tell the login just completed.
    _clear_google_oauth_session(session)
    if next_path:
        return _clear_google_oauth_transaction_cookie(
            dep("RedirectResponse")(success_redirect_url, status_code=302)
        )
    return _clear_google_oauth_transaction_cookie(dep("RedirectResponse")(
        _append_query_params(success_redirect_url, auth="success"),
        status_code=302,
    ))
