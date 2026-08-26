from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from services.cache import get_redis_client, mark_redis_unavailable


EMAIL_AUTH_TRANSACTION_COOKIE_NAME = "email_auth_transaction"
EMAIL_AUTH_TRANSACTION_KEY_PREFIX = "email_auth_transaction:"
EMAIL_AUTH_TRANSACTION_SCOPE_KEY = "_email_auth_transaction"
EMAIL_AUTH_TRANSACTION_TTL_SECONDS = 300
EMAIL_AUTH_TRANSACTION_MAX_ATTEMPTS = 5
EMAIL_AUTH_TRANSACTION_FLOW_LOGIN = "login"
EMAIL_AUTH_TRANSACTION_FLOW_REGISTRATION = "registration"
EMAIL_AUTH_UNAVAILABLE_ERROR = "メール認証を現在利用できません。"

EMAIL_AUTH_RESULT_SUCCESS = "success"
EMAIL_AUTH_RESULT_INVALID = "invalid"
EMAIL_AUTH_RESULT_EXPIRED = "expired"
EMAIL_AUTH_RESULT_EXHAUSTED = "exhausted"
EMAIL_AUTH_RESULT_MISSING = "missing"
EMAIL_AUTH_RESULT_UNAVAILABLE = "unavailable"
EMAIL_AUTH_RESULT_CONFLICT = "conflict"


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
    """認証コードを一般セッションから分離して短命Redisトランザクションへ保存する。"""
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
    """CookieのIDから有効なメール認証トランザクションを読み取る。"""
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


def _pipeline_watch_error(exc: Exception) -> bool:
    return exc.__class__.__name__ == "WatchError"


def verify_email_auth_transaction(
    transaction_id: str,
    submitted_code: str,
) -> EmailAuthVerificationResult:
    """コード検証と試行回数更新をRedisの楽観的排他で一つの状態遷移として行う。"""
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
                continue
            mark_redis_unavailable(exc)
            return EmailAuthVerificationResult(EMAIL_AUTH_RESULT_UNAVAILABLE)
        finally:
            if pipeline is not None:
                try:
                    pipeline.reset()
                except Exception:
                    pass
    return EmailAuthVerificationResult(EMAIL_AUTH_RESULT_CONFLICT)


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
