from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request

from blueprints.auth_common import (
    _append_query_params,
    _clear_google_oauth_session,
    _clear_google_oauth_state,
    _copy_default_tasks_after_login,
    _google_callback_redirect_target,
    _google_login_unavailable_response,
    _google_next_path,
    _redirect_to_login_after_google_failure,
)
from blueprints.auth_support import dep


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


def _clean_google_field(user_info: dict[str, Any], key: str) -> str:
    value = user_info.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _oauth_error_classes() -> tuple[type[BaseException], ...]:
    return (
        dep("GoogleAuthError"),
        dep("OAuth2Error"),
        dep("requests").RequestException,
        ValueError,
    )


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
        )
        authorization_url, state = flow.authorization_url(prompt="consent")
    except _oauth_error_classes():
        dep("logger").exception("Failed to initialize Google OAuth authorization URL.")
        return _google_login_unavailable_response()

    request.session["google_oauth_state"] = state
    request.session["google_redirect_uri"] = redirect_uri
    if safe_next_path:
        request.session[dep("GOOGLE_NEXT_PATH_SESSION_KEY")] = safe_next_path
    else:
        request.session.pop(dep("GOOGLE_NEXT_PATH_SESSION_KEY"), None)

    dep("logger").info(
        "Google OAuth login started. State: %s, Redirect URI: %s, Session ID: %s",
        state[:16] + "..." if state else "None",
        redirect_uri,
        request.scope.get("session_id", "unknown"),
    )
    return dep("RedirectResponse")(authorization_url, status_code=302)


async def google_callback(request: Request):
    session = request.session
    if dep("Flow") is None:
        return _redirect_to_login_after_google_failure(request, session)

    google_error = request.query_params.get("error")
    if google_error:
        dep("logger").warning(
            "Google OAuth callback: authorization error from Google: %s",
            google_error,
        )
        return _redirect_to_login_after_google_failure(request, session)

    state = session.get("google_oauth_state")
    dep("logger").info(
        "Google OAuth callback received. Session ID: %s, Has state: %s, Session keys: %s",
        request.scope.get("session_id", "unknown"),
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
        return _redirect_to_login_after_google_failure(request, session)

    redirect_uri = session.get("google_redirect_uri") or dep("os").getenv("GOOGLE_REDIRECT_URI")
    if not redirect_uri:
        redirect_uri = dep("url_for")(request, "auth.google_callback", _external=True)

    next_path = _google_next_path(session)
    client_config = dep("_google_client_config")()
    settings_error = dep("_validate_google_oauth_settings")(client_config)
    if settings_error:
        dep("logger").error(
            "Google OAuth callback aborted due to configuration error: %s",
            settings_error,
        )
        return _redirect_to_login_after_google_failure(
            request,
            session,
            redirect_uri=redirect_uri,
        )

    login_redirect_url = _google_callback_redirect_target(
        request,
        "/login",
        redirect_uri=redirect_uri,
    )
    if next_path:
        login_redirect_url = _append_query_params(login_redirect_url, next=next_path)

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
        )
    except _oauth_error_classes():
        dep("logger").exception("Failed to initialize Google OAuth callback flow.")
        return _redirect_to_login_after_google_failure(
            request,
            session,
            redirect_uri=redirect_uri,
        )

    authorization_response = dep("_build_google_authorization_response")(request, redirect_uri)
    try:
        await dep("run_blocking")(flow.fetch_token, authorization_response=authorization_response)
    except _oauth_error_classes():
        dep("logger").exception("Google OAuth token exchange failed.")
        _clear_google_oauth_session(session)
        return dep("RedirectResponse")(login_redirect_url, status_code=302)

    _clear_google_oauth_state(session)

    credentials = flow.credentials
    access_token = getattr(credentials, "token", "")
    if not isinstance(access_token, str) or not access_token:
        dep("logger").error("Google OAuth callback completed without an access token.")
        _clear_google_oauth_session(session)
        return dep("RedirectResponse")(login_redirect_url, status_code=302)

    try:
        user_info = await dep("run_blocking")(dep("_fetch_google_user_info"), access_token)
    except dep("requests").RequestException:
        dep("logger").exception("Failed to fetch Google user info.")
        _clear_google_oauth_session(session)
        return dep("RedirectResponse")(login_redirect_url, status_code=302)

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
        _clear_google_oauth_session(session)
        return dep("RedirectResponse")(login_redirect_url, status_code=302)

    try:
        user = await dep("run_blocking")(dep("get_user_by_google_id"), google_user_id)
        should_mark_verified = False
        should_offer_passkey_setup = False
        if user:
            user_id = user["id"]
            await dep("run_blocking")(dep("link_google_account"), user_id, google_user_id, email)
            should_mark_verified = not user.get("is_verified")
            should_offer_passkey_setup = should_mark_verified
        else:
            user = await dep("run_blocking")(dep("get_user_by_email"), email)
            if user:
                existing_google_user_id = (user.get("provider_user_id") or "").strip()
                if existing_google_user_id and existing_google_user_id != google_user_id:
                    dep("logger").warning(
                        "Google OAuth callback: conflicting google_user_id for email %s",
                        email,
                    )
                    _clear_google_oauth_session(session)
                    return dep("RedirectResponse")(login_redirect_url, status_code=302)
                user_id = user["id"]
                linked_google_account_for_first_time = not existing_google_user_id
                await dep("run_blocking")(dep("link_google_account"), user_id, google_user_id, email)
                should_mark_verified = not user.get("is_verified")
                should_offer_passkey_setup = (
                    linked_google_account_for_first_time or should_mark_verified
                )
            else:
                user_id = await dep("run_blocking")(
                    dep("create_user"),
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
                    _clear_google_oauth_session(session)
                    return dep("RedirectResponse")(login_redirect_url, status_code=302)
    except Exception:
        dep("logger").exception(
            "Google OAuth callback: unexpected error during user lookup/creation."
        )
        _clear_google_oauth_session(session)
        return dep("RedirectResponse")(login_redirect_url, status_code=302)

    dep("establish_authenticated_session")(request, int(user_id), email)

    try:
        await dep("run_blocking")(
            dep("update_user_profile_from_google_if_unset"),
            user_id,
            display_name or None,
            picture or None,
        )
    except Exception:
        dep("logger").exception("Google OAuth callback: failed to sync profile for user %s", user_id)

    if should_mark_verified:
        try:
            await dep("run_blocking")(dep("set_user_verified"), user_id)
        except Exception:
            dep("logger").exception("Google OAuth callback: failed to verify user %s", user_id)

    await _copy_default_tasks_after_login(user_id, context="Google OAuth callback")

    try:
        persisted_user = await dep("run_blocking")(dep("get_user_by_id"), user_id)
        if persisted_user:
            session["user_email"] = persisted_user["email"]
    except Exception:
        dep("logger").exception("Google OAuth callback: failed to refresh email for user %s", user_id)

    if should_offer_passkey_setup:
        passkey_setup_url = _google_callback_redirect_target(
            request,
            "/login",
            redirect_uri=redirect_uri,
        )
        passkey_setup_query = {
            "flow": "register",
            "offer_passkey_setup": "1",
            "provider": "google",
        }
        if next_path:
            passkey_setup_query["next"] = next_path
        _clear_google_oauth_session(session)
        return dep("RedirectResponse")(
            _append_query_params(passkey_setup_url, **passkey_setup_query),
            status_code=302,
        )

    _clear_google_oauth_session(session)
    if next_path:
        return dep("RedirectResponse")(success_redirect_url, status_code=302)
    return dep("RedirectResponse")(
        _append_query_params(success_redirect_url, auth="success"),
        status_code=302,
    )
