from __future__ import annotations

from fastapi import Request

from blueprints.auth_common import (
    _clear_google_oauth_session,
    _user_id_from_session,
)
from blueprints.auth_support import call_dependency, dep
from services.i18n import (
    PREFERRED_LOCALE_LOADED_SESSION_KEY,
    PREFERRED_LOCALE_SESSION_KEY,
    get_request_locale,
    normalize_locale,
)


async def _sign_out_current_account(request: Request) -> bool:
    """表示中のアカウントだけをログアウトし、待機中のアカウントがあればそちらを表示中にする。

    Sign out the active account only; when another account is parked, make it the active one.
    Returns whether another account took over.
    """
    parked_sessions = await dep("run_blocking")(dep("load_parked_sessions"), request)
    request.session.clear()
    for parked in parked_sessions or []:
        # 待機中に削除されたアカウントのセッションへは繰り上げない
        # Never fall back to the session of an account deleted while it was parked
        if await call_dependency("get_user_by_id", parked.user_id):
            dep("activate_parked_session")(request, parked, keep_current=False)
            return True
    return False


async def api_list_accounts(request: Request):
    current_user_id = _user_id_from_session(request.session)
    if current_user_id is None:
        return dep("jsonify")({"error": "ログインが必要です。"}, status_code=401)

    parked_sessions = await dep("run_blocking")(dep("load_parked_sessions"), request) or []
    accounts = []
    for user_id in (current_user_id, *(parked.user_id for parked in parked_sessions)):
        user = await call_dependency("get_user_by_id", user_id)
        if not user:
            continue
        accounts.append(
            {
                "user_id": user_id,
                "username": user.get("username") or "",
                "email": user.get("email") or "",
                "avatar_url": user.get("avatar_url") or "",
                "current": user_id == current_user_id,
            }
        )
    return dep("jsonify")({"accounts": accounts})


async def api_switch_account(request: Request):
    if _user_id_from_session(request.session) is None:
        return dep("jsonify")({"error": "ログインが必要です。"}, status_code=401)

    data, error_response = await dep("require_json_dict")(request)
    if error_response is not None:
        return error_response
    target_user_id = data.get("user_id")
    if not isinstance(target_user_id, int) or isinstance(target_user_id, bool):
        return dep("jsonify")({"error": "切り替え先のアカウントを指定してください。"}, status_code=400)

    parked_sessions = await dep("run_blocking")(dep("load_parked_sessions"), request)
    if parked_sessions is None:
        return dep("jsonify")({"error": "現在アカウントを切り替えられません。"}, status_code=503)
    target = next((parked for parked in parked_sessions if parked.user_id == target_user_id), None)
    if target is None or not await call_dependency("get_user_by_id", target.user_id):
        return dep("jsonify")(
            {"error": "このアカウントはログアウト済みです。もう一度ログインしてください。"},
            status_code=404,
        )

    dep("activate_parked_session")(request, target, keep_current=True)
    return dep("jsonify")({"status": "success"})


async def register_page(request: Request):
    return dep("redirect_to_frontend")(request)


async def api_current_user(request: Request):
    session = request.session
    if "user_id" not in session:
        return dep("jsonify")({"logged_in": False})

    user = await call_dependency("get_user_by_id", session["user_id"])
    if user:
        preferred_locale = normalize_locale(user.get("preferred_locale"))
        if preferred_locale is not None:
            session[PREFERRED_LOCALE_SESSION_KEY] = preferred_locale
            request.state.locale = preferred_locale
            request.state.persist_locale_cookie = True
        else:
            session.pop(PREFERRED_LOCALE_SESSION_KEY, None)
        session[PREFERRED_LOCALE_LOADED_SESSION_KEY] = True
        locale = preferred_locale or get_request_locale(request)
        return dep("jsonify")(
            {
                "logged_in": True,
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "username": user.get("username") or "",
                    "locale": locale,
                },
            }
        )

    session.pop("user_id", None)
    session.pop("user_email", None)
    session.pop("login_verification_code", None)
    session.pop("login_temp_user_id", None)
    session.pop("login_temp_email", None)
    session.pop("login_verification_code_issued_at", None)
    session.pop("login_verification_code_attempts", None)
    _clear_google_oauth_session(session)
    dep("clear_passkey_session")(session)
    dep("set_session_permanent")(session, False)
    return dep("jsonify")({"logged_in": False})


async def api_delete_user_account(request: Request):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return dep("jsonify")({"error": "ログインが必要です。"}, status_code=401)

    data, error_response = await dep("require_json_dict")(request)
    if error_response is not None:
        return error_response

    confirmation = str(data.get("confirmation") or "").strip()
    if confirmation != dep("ACCOUNT_DELETE_CONFIRMATION_TEXT"):
        return dep("jsonify")({"error": "確認文字列が一致しません。"}, status_code=400)

    try:
        deleted = await call_dependency("delete_user_account", user_id)
    except Exception:
        return dep("log_and_internal_server_error")(
            dep("logger"),
            "Failed to delete user account.",
            message="アカウント削除に失敗しました。",
        )

    await _sign_out_current_account(request)
    if not deleted:
        return dep("jsonify")({"error": "削除対象のアカウントが見つかりませんでした。"}, status_code=404)
    # user_id は、このブラウザの切り替えメニューから削除済みアカウントの控えを外すために返す
    # user_id lets the browser drop the deleted account from its switcher record
    return dep("jsonify")({"message": "アカウントを削除しました。", "user_id": user_id})


async def login(request: Request):
    return dep("redirect_to_frontend")(request)


async def logout(request: Request):
    if await _sign_out_current_account(request):
        return dep("RedirectResponse")(dep("frontend_url")("/"), status_code=302)
    return dep("RedirectResponse")(dep("frontend_login_url")(), status_code=302)
