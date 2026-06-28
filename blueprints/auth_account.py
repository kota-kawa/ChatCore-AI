from __future__ import annotations

from fastapi import Request

from blueprints.auth_common import (
    _clear_google_oauth_session,
    _user_id_from_session,
)
from blueprints.auth_support import dep


async def register_page(request: Request):
    return dep("redirect_to_frontend")(request)


async def api_current_user(request: Request):
    session = request.session
    if "user_id" not in session:
        return dep("jsonify")({"logged_in": False})

    user = await dep("run_blocking")(dep("get_user_by_id"), session["user_id"])
    if user:
        return dep("jsonify")(
            {
                "logged_in": True,
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "username": user.get("username") or "",
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
        deleted = await dep("run_blocking")(dep("delete_user_account"), user_id)
    except Exception:
        return dep("log_and_internal_server_error")(
            dep("logger"),
            "Failed to delete user account.",
            message="アカウント削除に失敗しました。",
        )

    request.session.clear()
    if not deleted:
        return dep("jsonify")({"error": "削除対象のアカウントが見つかりませんでした。"}, status_code=404)
    return dep("jsonify")({"message": "アカウントを削除しました。"})


async def login(request: Request):
    return dep("redirect_to_frontend")(request)


async def logout(request: Request):
    request.session.clear()
    return dep("RedirectResponse")(dep("frontend_login_url")(), status_code=302)
