from __future__ import annotations

from typing import Any

from fastapi import Request

from blueprints.auth_support import dep


def clear_legacy_email_auth_session(session: dict[str, Any]) -> None:
    """新しいメール認証開始時に旧セッション由来の一時状態を全て消去する。"""
    for key in (
        "login_verification_code",
        "login_temp_user_id",
        "login_temp_email",
        "login_verification_code_issued_at",
        "login_verification_code_attempts",
        "login_verification_locale",
        "verification_code",
        "temp_user_id",
        "temp_email",
        "verification_code_issued_at",
        "verification_code_attempts",
        "verification_locale",
    ):
        session.pop(key, None)


async def load_dedicated_email_auth_transaction(
    request: Request,
    expected_flow: str,
) -> tuple[Any | None, bool]:
    """専用Cookieに紐づくメール認証トランザクションを読み取る。"""
    transaction = request.scope.pop(dep("EMAIL_AUTH_TRANSACTION_SCOPE_KEY"), None)
    transaction_id = request.cookies.get(dep("EMAIL_AUTH_TRANSACTION_COOKIE_NAME"))
    dedicated_requested = transaction is not None or transaction_id is not None
    if transaction is None and transaction_id is not None:
        transaction = await dep("run_blocking")(
            dep("get_email_auth_transaction"),
            transaction_id,
        )
    if not dedicated_requested:
        return None, False
    if transaction is None or transaction.flow != expected_flow:
        return None, True
    if transaction_id is not None and transaction.transaction_id != transaction_id:
        return None, True
    return transaction, True


def email_auth_failure_response(
    message: str,
    *,
    status_code: int,
    clear_cookie: bool,
) -> Any:
    response = dep("jsonify")(
        {"status": "fail", "error": message},
        status_code=status_code,
    )
    if clear_cookie:
        dep("clear_email_auth_transaction_cookie")(response)
    return response


def email_auth_unavailable_response(*, clear_cookie: bool = False) -> Any:
    return email_auth_failure_response(
        dep("EMAIL_AUTH_UNAVAILABLE_ERROR"),
        status_code=503,
        clear_cookie=clear_cookie,
    )
