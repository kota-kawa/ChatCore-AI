from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Request

from blueprints.auth_support import dep


def _clear_login_verification_session(session: dict[str, Any]) -> None:
    session.pop("login_verification_code", None)
    session.pop("login_temp_user_id", None)
    session.pop("login_temp_email", None)
    session.pop("login_verification_code_issued_at", None)
    session.pop("login_verification_code_attempts", None)


def _clear_google_oauth_session(session: dict[str, Any]) -> None:
    session.pop("google_oauth_state", None)
    session.pop("google_redirect_uri", None)
    session.pop(dep("GOOGLE_CODE_VERIFIER_SESSION_KEY"), None)
    session.pop(dep("GOOGLE_NEXT_PATH_SESSION_KEY"), None)


def _clear_google_oauth_state(session: dict[str, Any]) -> None:
    session.pop("google_oauth_state", None)
    session.pop("google_redirect_uri", None)
    session.pop(dep("GOOGLE_CODE_VERIFIER_SESSION_KEY"), None)


def _google_login_unavailable_response() -> Any:
    return dep("jsonify")({"error": dep("GOOGLE_LOGIN_UNAVAILABLE_ERROR")}, status_code=503)


def _passkey_unavailable_response() -> Any:
    return dep("jsonify")(
        {"status": "fail", "error": dep("PASSKEY_UNAVAILABLE_ERROR")},
        status_code=503,
    )


def _resolve_auth_limit_service(request: Request, service: Any | None) -> Any:
    if isinstance(service, dep("AuthLimitService")):
        return service
    return dep("get_auth_limit_service")(request)


def _resolve_llm_daily_limit_service(request: Request, service: Any | None) -> Any:
    if isinstance(service, dep("LlmDailyLimitService")):
        return service
    return dep("get_llm_daily_limit_service")(request)


def _user_id_from_session(session: dict[str, Any]) -> int | None:
    user_id = session.get("user_id")
    if isinstance(user_id, int):
        return user_id
    return None


async def _copy_default_tasks_after_login(user_id: int, *, context: str) -> None:
    try:
        await dep("run_blocking")(dep("copy_default_tasks_for_user"), user_id)
    except Exception:
        dep("logger").exception(
            "%s: failed to copy default tasks for user %s",
            context,
            user_id,
        )


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


def _google_next_path(session: dict[str, Any]) -> str | None:
    next_path = session.get(dep("GOOGLE_NEXT_PATH_SESSION_KEY"))
    if not isinstance(next_path, str) or not next_path:
        return None
    return dep("sanitize_next_path")(next_path, default="/")


def _redirect_to_login_after_google_failure(
    request: Request,
    session: dict[str, Any],
    *,
    redirect_uri: str | None = None,
) -> Any:
    next_path = _google_next_path(session)
    target_url = _google_callback_redirect_target(
        request,
        "/login",
        redirect_uri=redirect_uri,
    )
    if next_path:
        target_url = _append_query_params(target_url, next=next_path)
    _clear_google_oauth_state(session)
    return dep("RedirectResponse")(target_url, status_code=302)
