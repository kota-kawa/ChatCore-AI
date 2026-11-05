"""メール認証フロー（ログイン・登録の認証コード）で共有するセッション掃除・トランザクション読み取り・失敗応答のヘルパー。

Shared helpers for the email-auth flows (login/signup verification codes): session cleanup, transaction loading, and failure responses.
Used by blueprints/auth_email.py and blueprints/verification.py.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from blueprints.auth_support import dep


def clear_legacy_email_auth_session(session: dict[str, Any]) -> None:
    """新しいメール認証開始時に旧セッション由来の一時状態を全て消去する。

    Clear every temporary value left in the session by earlier email-auth flows when a new one starts.
    """
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
    """専用Cookieに紐づくメール認証トランザクションを読み取る。

    戻り値は (トランザクション, 専用方式が要求されたか)。要求されたのに有効なトランザクションが無い（flow 不一致・ID 不一致を含む）
    場合は (None, True) を返し、呼び出し側が旧セッション方式へ落ちずに失敗として扱えるようにする。
    リクエスト scope に積まれた検証済みトランザクションがあれば、DB 参照より優先する。

    Read the email-auth transaction bound to the dedicated cookie.

    Returns (transaction, dedicated_requested). When the dedicated mode was requested but no valid transaction exists
    (including a flow or ID mismatch), it returns (None, True) so callers fail instead of falling back to the legacy
    session mode. A transaction already placed on the request scope takes precedence over a database lookup.
    """
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
    """メール認証の失敗を JSON で返し、必要なら専用Cookieも削除する。

    Build a JSON failure response for email auth, optionally clearing the dedicated cookie.
    """
    response = dep("jsonify")(
        {"status": "fail", "error": message},
        status_code=status_code,
    )
    if clear_cookie:
        dep("clear_email_auth_transaction_cookie")(response)
    return response


def email_auth_unavailable_response(*, clear_cookie: bool = False) -> Any:
    """メール認証が利用できない場合の 503 応答を返す。

    Return the 503 response used when email authentication is unavailable.
    """
    return email_auth_failure_response(
        dep("EMAIL_AUTH_UNAVAILABLE_ERROR"),
        status_code=503,
        clear_cookie=clear_cookie,
    )
