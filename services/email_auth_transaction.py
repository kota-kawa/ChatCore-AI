"""メール認証コードのログイン／登録フローで使う、短命な認証トランザクションを Redis で管理する。
認証コードそのもの（のハッシュ）、試行回数、有効期限を一般のセッションから分離して持ち、
検証と試行回数の更新を楽観的排他で 1 つの状態遷移として行う。Cookie には ID だけを載せる。

Manages short-lived email-auth transactions in Redis for the email-code login and registration flows.
Keeps the code digest, attempt count and expiry apart from the general session, and performs verification
plus attempt counting as one state transition under optimistic locking. Only the id travels in the cookie.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from services.cache import get_redis_client, mark_redis_unavailable

logger = logging.getLogger(__name__)

# 日本語: Redis のキー接頭辞・有効期間（秒）・誤入力の上限回数、およびフロー（ログイン／登録）の種別。
# English: Redis key prefix, lifetime (seconds), maximum wrong attempts, and the flow kinds (login / registration).
EMAIL_AUTH_TRANSACTION_COOKIE_NAME = "email_auth_transaction"
EMAIL_AUTH_TRANSACTION_KEY_PREFIX = "email_auth_transaction:"
EMAIL_AUTH_TRANSACTION_SCOPE_KEY = "_email_auth_transaction"
EMAIL_AUTH_TRANSACTION_TTL_SECONDS = 300
EMAIL_AUTH_TRANSACTION_MAX_ATTEMPTS = 5
EMAIL_AUTH_TRANSACTION_FLOW_LOGIN = "login"
EMAIL_AUTH_TRANSACTION_FLOW_REGISTRATION = "registration"
EMAIL_AUTH_UNAVAILABLE_ERROR = "メール認証を現在利用できません。"

# 日本語: 検証結果の状態。success=一致、invalid=不一致（再入力可）、expired=期限切れ、exhausted=試行回数超過、
# missing=存在しない・壊れている、unavailable=Redis が使えない、conflict=同時更新が続いて確定できない。
# English: Verification outcomes: success (match), invalid (mismatch, may retry), expired, exhausted (too many attempts),
# missing (absent or corrupt), unavailable (Redis down) and conflict (concurrent updates never settled).
EMAIL_AUTH_RESULT_SUCCESS = "success"
EMAIL_AUTH_RESULT_INVALID = "invalid"
EMAIL_AUTH_RESULT_EXPIRED = "expired"
EMAIL_AUTH_RESULT_EXHAUSTED = "exhausted"
EMAIL_AUTH_RESULT_MISSING = "missing"
EMAIL_AUTH_RESULT_UNAVAILABLE = "unavailable"
EMAIL_AUTH_RESULT_CONFLICT = "conflict"


# 日本語: Redis に保存する 1 回分の認証トランザクション。コードそのものではなくハッシュ（code_digest）を持つ。
# English: One auth transaction stored in Redis; it holds the code's hash (code_digest), not the code itself.
@dataclass(frozen=True)
class EmailAuthTransaction:
    transaction_id: str
    flow: str
    user_id: int
    email: str
    code_digest: str
    issued_at: int
    attempts: int
    locale: str | None


# 日本語: 検証の結果。status は上の EMAIL_AUTH_RESULT_*、transaction は判明している場合だけ入る。
# English: Result of a verification: status is one of EMAIL_AUTH_RESULT_*, transaction is set when known.
@dataclass(frozen=True)
class EmailAuthVerificationResult:
    status: str
    transaction: EmailAuthTransaction | None = None


def _transaction_key(transaction_id: str) -> str:
    return f"{EMAIL_AUTH_TRANSACTION_KEY_PREFIX}{transaction_id}"


def _code_digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _serialize_transaction(transaction: EmailAuthTransaction) -> str:
    return json.dumps(
        {
            "flow": transaction.flow,
            "user_id": transaction.user_id,
            "email": transaction.email,
            "code_digest": transaction.code_digest,
            "issued_at": transaction.issued_at,
            "attempts": transaction.attempts,
            "locale": transaction.locale,
        },
        ensure_ascii=False,
    )


# 日本語: Redis の値を厳密に検証して復元する。形が少しでも不正なら missing として扱い、期限切れは expired を返す。
# English: Strictly validate and rebuild the Redis value; any malformed field is treated as missing, and an old one yields expired.
def _decode_transaction(
    transaction_id: str,
    raw_payload: Any,
) -> tuple[EmailAuthTransaction | None, str]:
    if raw_payload is None:
        return None, EMAIL_AUTH_RESULT_MISSING

    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        return None, EMAIL_AUTH_RESULT_MISSING
    if not isinstance(payload, dict):
        return None, EMAIL_AUTH_RESULT_MISSING

    flow = payload.get("flow")
    user_id = payload.get("user_id")
    email = payload.get("email")
    code_digest = payload.get("code_digest")
    issued_at = payload.get("issued_at")
    attempts = payload.get("attempts")
    locale = payload.get("locale")
    if flow not in {
        EMAIL_AUTH_TRANSACTION_FLOW_LOGIN,
        EMAIL_AUTH_TRANSACTION_FLOW_REGISTRATION,
    }:
        return None, EMAIL_AUTH_RESULT_MISSING
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        return None, EMAIL_AUTH_RESULT_MISSING
    if not isinstance(email, str) or not email:
        return None, EMAIL_AUTH_RESULT_MISSING
    if not isinstance(code_digest, str) or len(code_digest) != 64:
        return None, EMAIL_AUTH_RESULT_MISSING
    if not isinstance(issued_at, int) or isinstance(issued_at, bool) or issued_at <= 0:
        return None, EMAIL_AUTH_RESULT_MISSING
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
        return None, EMAIL_AUTH_RESULT_MISSING
    if locale is not None and not isinstance(locale, str):
        locale = None

    transaction = EmailAuthTransaction(
        transaction_id=transaction_id,
        flow=flow,
        user_id=user_id,
        email=email,
        code_digest=code_digest,
        issued_at=issued_at,
        attempts=attempts,
        locale=locale,
    )
    if int(time.time()) - issued_at >= EMAIL_AUTH_TRANSACTION_TTL_SECONDS:
        return transaction, EMAIL_AUTH_RESULT_EXPIRED
    return transaction, EMAIL_AUTH_RESULT_SUCCESS


# 日本語: 試行回数を更新して書き直すときも元の有効期限を延ばさないよう、残り秒数を計算する（最低 1 秒）。
# English: Remaining lifetime in seconds (minimum 1), so rewriting after an attempt does not extend the original expiry.
def _remaining_ttl(issued_at: int) -> int:
    elapsed = max(int(time.time()) - issued_at, 0)
    return max(EMAIL_AUTH_TRANSACTION_TTL_SECONDS - elapsed, 1)


def store_email_auth_transaction(
    *,
    flow: str,
    user_id: int,
    email: str,
    code: str,
    locale: str | None,
) -> str | None:
    """認証コードを一般セッションから分離して短命Redisトランザクションへ保存する。
    入力が不正、または Redis が使えない場合は None を返す。成功時は Cookie に載せるトランザクション ID を返す。

    Store the auth code in a short-lived Redis transaction, separate from the general session.
    Returns None for invalid input or when Redis is unavailable; otherwise the transaction id for the cookie.
    """
    if flow not in {
        EMAIL_AUTH_TRANSACTION_FLOW_LOGIN,
        EMAIL_AUTH_TRANSACTION_FLOW_REGISTRATION,
    }:
        return None
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        return None
    if not isinstance(email, str) or not email:
        return None
    if not isinstance(code, str) or not code:
        return None
    if locale is not None and not isinstance(locale, str):
        return None

    redis_client = get_redis_client()
    if redis_client is None:
        return None

    transaction_id = secrets.token_urlsafe(32)
    transaction = EmailAuthTransaction(
        transaction_id=transaction_id,
        flow=flow,
        user_id=user_id,
        email=email,
        code_digest=_code_digest(code),
        issued_at=int(time.time()),
        attempts=0,
        locale=locale,
    )
    try:
        stored = redis_client.set(
            _transaction_key(transaction_id),
            _serialize_transaction(transaction),
            ex=EMAIL_AUTH_TRANSACTION_TTL_SECONDS,
            nx=True,
        )
    except Exception as exc:
        mark_redis_unavailable(exc)
        return None
    return transaction_id if stored else None


def get_email_auth_transaction(transaction_id: str) -> EmailAuthTransaction | None:
    """CookieのIDから有効なメール認証トランザクションを読み取る。
    期限切れのものは削除して None を返す。

    Read a valid email-auth transaction from the cookie's id.
    An expired one is deleted and None is returned.
    """
    if not isinstance(transaction_id, str) or not transaction_id:
        return None
    redis_client = get_redis_client()
    if redis_client is None:
        return None
    try:
        raw_payload = redis_client.get(_transaction_key(transaction_id))
    except Exception as exc:
        mark_redis_unavailable(exc)
        return None

    transaction, status = _decode_transaction(transaction_id, raw_payload)
    if status == EMAIL_AUTH_RESULT_EXPIRED:
        delete_email_auth_transaction(transaction_id)
        return None
    if status != EMAIL_AUTH_RESULT_SUCCESS:
        return None
    return transaction


def delete_email_auth_transaction(transaction_id: str) -> None:
    if not isinstance(transaction_id, str) or not transaction_id:
        return
    redis_client = get_redis_client()
    if redis_client is None:
        return
    try:
        redis_client.delete(_transaction_key(transaction_id))
    except Exception as exc:
        mark_redis_unavailable(exc)


# 日本語: redis-py の WatchError（監視中のキーが他で更新された）かを、クラス名で判定する。
# English: Detect redis-py's WatchError (the watched key was changed elsewhere) by class name.
def _pipeline_watch_error(exc: Exception) -> bool:
    return exc.__class__.__name__ == "WatchError"


def verify_email_auth_transaction(
    transaction_id: str,
    submitted_code: str,
) -> EmailAuthVerificationResult:
    """コード検証と試行回数更新をRedisの楽観的排他で一つの状態遷移として行う。
    一致・期限切れ・試行回数超過のときはトランザクションを削除する（コードは使い捨て）。不一致なら試行回数を
    1 増やして保存する。他で更新された場合は最大 3 回までやり直し、それでも確定しなければ conflict を返す。

    Verify the code and update the attempt count as one state transition using Redis optimistic locking.
    The transaction is deleted on match, expiry or too many attempts (codes are single-use); a mismatch
    stores an incremented attempt count. Concurrent modification is retried up to three times, then conflict is returned.
    """
    if not isinstance(transaction_id, str) or not transaction_id:
        return EmailAuthVerificationResult(EMAIL_AUTH_RESULT_MISSING)
    if not isinstance(submitted_code, str):
        submitted_code = str(submitted_code)

    redis_client = get_redis_client()
    if redis_client is None:
        return EmailAuthVerificationResult(EMAIL_AUTH_RESULT_UNAVAILABLE)
    pipeline_factory = getattr(redis_client, "pipeline", None)
    if not callable(pipeline_factory):
        return EmailAuthVerificationResult(EMAIL_AUTH_RESULT_UNAVAILABLE)

    key = _transaction_key(transaction_id)
    submitted_digest = _code_digest(submitted_code)
    for _ in range(3):
        pipeline = None
        try:
            pipeline = pipeline_factory()
            pipeline.watch(key)
            raw_payload = pipeline.get(key)
            transaction, status = _decode_transaction(transaction_id, raw_payload)
            if transaction is None:
                return EmailAuthVerificationResult(status)
            if status == EMAIL_AUTH_RESULT_EXPIRED:
                pipeline.multi()
                pipeline.delete(key)
                pipeline.execute()
                return EmailAuthVerificationResult(EMAIL_AUTH_RESULT_EXPIRED)
            if transaction.attempts >= EMAIL_AUTH_TRANSACTION_MAX_ATTEMPTS:
                pipeline.multi()
                pipeline.delete(key)
                pipeline.execute()
                return EmailAuthVerificationResult(EMAIL_AUTH_RESULT_EXHAUSTED)

            if hmac.compare_digest(submitted_digest, transaction.code_digest):
                pipeline.multi()
                pipeline.delete(key)
                pipeline.execute()
                return EmailAuthVerificationResult(
                    EMAIL_AUTH_RESULT_SUCCESS,
                    transaction=transaction,
                )

            next_attempts = transaction.attempts + 1
            if next_attempts >= EMAIL_AUTH_TRANSACTION_MAX_ATTEMPTS:
                pipeline.multi()
                pipeline.delete(key)
                pipeline.execute()
                return EmailAuthVerificationResult(EMAIL_AUTH_RESULT_EXHAUSTED)

            updated_transaction = EmailAuthTransaction(
                transaction_id=transaction.transaction_id,
                flow=transaction.flow,
                user_id=transaction.user_id,
                email=transaction.email,
                code_digest=transaction.code_digest,
                issued_at=transaction.issued_at,
                attempts=next_attempts,
                locale=transaction.locale,
            )
            pipeline.multi()
            pipeline.set(
                key,
                _serialize_transaction(updated_transaction),
                ex=_remaining_ttl(transaction.issued_at),
            )
            pipeline.execute()
            return EmailAuthVerificationResult(
                EMAIL_AUTH_RESULT_INVALID,
                transaction=updated_transaction,
            )
        except Exception as exc:
            if _pipeline_watch_error(exc):
                # リトライループ内なので debug 止まりにしてログ洪水を避ける
                # Keep this at debug because it sits inside the retry loop and would otherwise flood the log
                logger.debug("Email auth transaction was modified concurrently; retrying the code verification.")
                continue
            mark_redis_unavailable(exc)
            return EmailAuthVerificationResult(EMAIL_AUTH_RESULT_UNAVAILABLE)
        finally:
            if pipeline is not None:
                with contextlib.suppress(Exception):
                    pipeline.reset()
    return EmailAuthVerificationResult(EMAIL_AUTH_RESULT_CONFLICT)


# 日本語: ID を載せる Cookie を設定する。JavaScript から読めない（httponly）ようにし、有効期間はトランザクションと同じにする。
# English: Set the cookie carrying the id: httponly (unreadable from JavaScript) with the same lifetime as the transaction.
def set_email_auth_transaction_cookie(response: Any, transaction_id: str, *, secure: bool) -> Any:
    response.set_cookie(
        EMAIL_AUTH_TRANSACTION_COOKIE_NAME,
        transaction_id,
        max_age=EMAIL_AUTH_TRANSACTION_TTL_SECONDS,
        path="/",
        httponly=True,
        secure=secure,
        samesite="none" if secure else "lax",
    )
    return response


def clear_email_auth_transaction_cookie(response: Any) -> Any:
    response.delete_cookie(EMAIL_AUTH_TRANSACTION_COOKIE_NAME, path="/")
    return response
