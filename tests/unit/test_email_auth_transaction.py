import asyncio
import hashlib
import json
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.auth import api_verify_email_code, api_verify_login_code
from blueprints.verification import api_verify_registration_code
from services.email_auth_transaction import (
    EMAIL_AUTH_RESULT_CONFLICT,
    EMAIL_AUTH_RESULT_EXHAUSTED,
    EMAIL_AUTH_RESULT_INVALID,
    EMAIL_AUTH_RESULT_MISSING,
    EMAIL_AUTH_RESULT_SUCCESS,
    EMAIL_AUTH_RESULT_UNAVAILABLE,
    EMAIL_AUTH_TRANSACTION_FLOW_LOGIN,
    EMAIL_AUTH_TRANSACTION_FLOW_REGISTRATION,
    EMAIL_AUTH_TRANSACTION_MAX_ATTEMPTS,
    EMAIL_AUTH_TRANSACTION_TTL_SECONDS,
    EmailAuthTransaction,
    EmailAuthVerificationResult,
    clear_email_auth_transaction_cookie,
    get_email_auth_transaction,
    set_email_auth_transaction_cookie,
    store_email_auth_transaction,
    verify_email_auth_transaction,
)
from services.web import jsonify
from tests.helpers.request_helpers import build_request


class WatchError(Exception):
    pass


class DummyRedisPipeline:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.watched = {}
        self.commands = []

    def watch(self, key):
        self.watched[key] = self.redis_client.versions.get(key, 0)

    def get(self, key):
        return self.redis_client.get(key)

    def multi(self):
        self.commands = []

    def delete(self, key):
        self.commands.append(("delete", key))

    def set(self, key, value, ex=None):
        self.commands.append(("set", key, value, ex))

    def execute(self):
        if any(
            self.redis_client.versions.get(key, 0) != version
            for key, version in self.watched.items()
        ):
            raise WatchError("transaction changed")
        for command in self.commands:
            if command[0] == "delete":
                self.redis_client.delete(command[1])
            else:
                _, key, value, expiry = command
                self.redis_client.set(key, value, ex=expiry)
        return []

    def reset(self):
        self.commands = []
        self.watched = {}


class DummyRedis:
    def __init__(self):
        self.store = {}
        self.expiry = {}
        self.versions = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        self.expiry[key] = ex
        self.versions[key] = self.versions.get(key, 0) + 1
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        existed = key in self.store
        self.store.pop(key, None)
        self.expiry.pop(key, None)
        if existed:
            self.versions[key] = self.versions.get(key, 0) + 1
        return int(existed)

    def pipeline(self):
        return DummyRedisPipeline(self)


class AlwaysConflictPipeline(DummyRedisPipeline):
    def execute(self):
        raise WatchError("transaction changed")


class AlwaysConflictRedis(DummyRedis):
    def pipeline(self):
        return AlwaysConflictPipeline(self)


def make_request(path, code, *, flow_cookie=None, session=None):
    headers = []
    if flow_cookie:
        headers.append((b"cookie", f"email_auth_transaction={flow_cookie}".encode("ascii")))
    return build_request(
        method="POST",
        path=path,
        json_body={"authCode": code},
        headers=headers,
        session=session,
    )


def transaction(*, flow=EMAIL_AUTH_TRANSACTION_FLOW_LOGIN):
    return EmailAuthTransaction(
        transaction_id="email-transaction",
        flow=flow,
        user_id=12,
        email="user@example.com",
        code_digest="0" * 64,
        issued_at=1000,
        attempts=0,
        locale="ja",
    )


class EmailAuthTransactionServiceTestCase(unittest.TestCase):
    def test_transaction_stores_digest_with_ttl_and_consumes_once(self):
        redis_client = DummyRedis()
        with patch(
            "services.email_auth_transaction.get_redis_client",
            return_value=redis_client,
        ):
            with patch("services.email_auth_transaction.time.time", return_value=1000):
                transaction_id = store_email_auth_transaction(
                    flow=EMAIL_AUTH_TRANSACTION_FLOW_LOGIN,
                    user_id=12,
                    email="user@example.com",
                    code="123456",
                    locale="ja",
                )

            self.assertIsNotNone(transaction_id)
            key = f"email_auth_transaction:{transaction_id}"
            payload = json.loads(redis_client.store[key])
            self.assertNotIn("123456", redis_client.store[key])
            self.assertEqual(
                payload["code_digest"],
                hashlib.sha256(b"123456").hexdigest(),
            )
            self.assertEqual(redis_client.expiry[key], EMAIL_AUTH_TRANSACTION_TTL_SECONDS)

            with patch("services.email_auth_transaction.time.time", return_value=1000):
                stored = get_email_auth_transaction(transaction_id)
                result = verify_email_auth_transaction(transaction_id, "123456")
            self.assertEqual(stored.email, "user@example.com")
            self.assertEqual(result.status, EMAIL_AUTH_RESULT_SUCCESS)
            self.assertEqual(result.transaction.user_id, 12)
            self.assertIsNone(get_email_auth_transaction(transaction_id))
            self.assertEqual(
                verify_email_auth_transaction(transaction_id, "123456").status,
                EMAIL_AUTH_RESULT_MISSING,
            )

    def test_invalid_code_increments_attempts_without_touching_general_session(self):
        redis_client = DummyRedis()
        with patch(
            "services.email_auth_transaction.get_redis_client",
            return_value=redis_client,
        ):
            transaction_id = store_email_auth_transaction(
                flow=EMAIL_AUTH_TRANSACTION_FLOW_REGISTRATION,
                user_id=12,
                email="new-user@example.com",
                code="123456",
                locale="en",
            )

            result = verify_email_auth_transaction(transaction_id, "000000")
            self.assertEqual(result.status, EMAIL_AUTH_RESULT_INVALID)
            self.assertEqual(result.transaction.attempts, 1)
            self.assertEqual(get_email_auth_transaction(transaction_id).attempts, 1)

            for _ in range(EMAIL_AUTH_TRANSACTION_MAX_ATTEMPTS - 1):
                result = verify_email_auth_transaction(transaction_id, "000000")
            self.assertEqual(result.status, EMAIL_AUTH_RESULT_EXHAUSTED)
            self.assertIsNone(get_email_auth_transaction(transaction_id))

    def test_expired_transaction_is_removed(self):
        redis_client = DummyRedis()
        with patch(
            "services.email_auth_transaction.get_redis_client",
            return_value=redis_client,
        ):
            with patch("services.email_auth_transaction.time.time", return_value=1000):
                transaction_id = store_email_auth_transaction(
                    flow=EMAIL_AUTH_TRANSACTION_FLOW_LOGIN,
                    user_id=12,
                    email="user@example.com",
                    code="123456",
                    locale=None,
                )
            with patch("services.email_auth_transaction.time.time", return_value=1300):
                self.assertIsNone(get_email_auth_transaction(transaction_id))
                self.assertEqual(
                    verify_email_auth_transaction(transaction_id, "123456").status,
                    EMAIL_AUTH_RESULT_MISSING,
                )

    def test_redis_unavailable_fails_closed(self):
        with patch("services.email_auth_transaction.get_redis_client", return_value=None):
            self.assertIsNone(
                store_email_auth_transaction(
                    flow=EMAIL_AUTH_TRANSACTION_FLOW_LOGIN,
                    user_id=12,
                    email="user@example.com",
                    code="123456",
                    locale=None,
                )
            )
            self.assertEqual(
                verify_email_auth_transaction("missing", "123456").status,
                EMAIL_AUTH_RESULT_UNAVAILABLE,
            )

    def test_concurrent_transaction_conflict_is_reported_without_overwriting_state(self):
        redis_client = AlwaysConflictRedis()
        with patch(
            "services.email_auth_transaction.get_redis_client",
            return_value=redis_client,
        ):
            transaction_id = store_email_auth_transaction(
                flow=EMAIL_AUTH_TRANSACTION_FLOW_LOGIN,
                user_id=12,
                email="user@example.com",
                code="123456",
                locale=None,
            )

            result = verify_email_auth_transaction(transaction_id, "000000")
            stored = get_email_auth_transaction(transaction_id)

        self.assertEqual(result.status, EMAIL_AUTH_RESULT_CONFLICT)
        self.assertEqual(stored.attempts, 0)

    def test_transaction_cookie_is_http_only_and_clears_cleanly(self):
        response = set_email_auth_transaction_cookie(
            jsonify({"status": "success"}),
            "email-transaction",
            secure=True,
        )
        cookie = response.headers["set-cookie"]
        self.assertIn("email_auth_transaction=email-transaction", cookie)
        self.assertIn("Max-Age=300", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("samesite=none", cookie.lower())

        clear_email_auth_transaction_cookie(response)
        self.assertTrue(
            any(
                key.lower() == b"set-cookie" and b'email_auth_transaction=""' in value
                for key, value in response.raw_headers
            )
        )


class DedicatedEmailAuthRouteTestCase(unittest.TestCase):
    def test_login_verification_uses_dedicated_transaction_without_session_code(self):
        session = {"pre_auth": True}
        request = make_request(
            "/api/verify_login_code",
            "123456",
            flow_cookie="email-transaction",
            session=session,
        )
        current_transaction = transaction()
        successful_verification = EmailAuthVerificationResult(
            EMAIL_AUTH_RESULT_SUCCESS,
            transaction=current_transaction,
        )

        with patch("blueprints.auth.get_email_auth_transaction", return_value=current_transaction):
            with patch(
                "blueprints.auth.verify_email_auth_transaction",
                return_value=successful_verification,
            ):
                with patch("blueprints.auth.consume_verification_attempt_limit", return_value=(True, None)):
                    with patch(
                        "blueprints.auth.get_user_by_id",
                        return_value={"id": 12, "email": "user@example.com", "is_verified": True},
                    ):
                        with patch("blueprints.auth.copy_default_tasks_for_user"):
                            response = asyncio.run(api_verify_login_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["flow"], "login")
        self.assertEqual(session["user_id"], 12)
        self.assertNotIn("login_verification_code", session)
        self.assertTrue(
            any(
                key.lower() == b"set-cookie" and b'email_auth_transaction=""' in value
                for key, value in response.raw_headers
            )
        )

    def test_registration_verification_uses_dedicated_transaction_without_session_code(self):
        session = {"pre_auth": True}
        request = make_request(
            "/api/verify_registration_code",
            "123456",
            flow_cookie="email-transaction",
            session=session,
        )
        current_transaction = transaction(flow=EMAIL_AUTH_TRANSACTION_FLOW_REGISTRATION)
        successful_verification = EmailAuthVerificationResult(
            EMAIL_AUTH_RESULT_SUCCESS,
            transaction=current_transaction,
        )

        with patch("blueprints.auth.get_email_auth_transaction", return_value=current_transaction):
            with patch(
                "blueprints.verification.verify_email_auth_transaction",
                return_value=successful_verification,
            ):
                with patch(
                    "blueprints.verification.consume_verification_attempt_limit",
                    return_value=(True, None),
                ):
                    with patch(
                        "blueprints.verification.get_user_by_id",
                        return_value={"id": 12, "email": "user@example.com", "is_verified": False},
                    ):
                        with patch("blueprints.verification.set_user_verified"):
                            with patch("blueprints.verification.copy_default_tasks_for_user"):
                                response = asyncio.run(api_verify_registration_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["flow"], "register")
        self.assertEqual(session["user_id"], 12)
        self.assertNotIn("verification_code", session)
        self.assertTrue(
            any(
                key.lower() == b"set-cookie" and b'email_auth_transaction=""' in value
                for key, value in response.raw_headers
            )
        )

    def test_invalid_login_code_keeps_dedicated_transaction_and_not_general_session(self):
        session = {"pre_auth": True}
        request = make_request(
            "/api/verify_login_code",
            "000000",
            flow_cookie="email-transaction",
            session=session,
        )
        current_transaction = transaction()
        failed_verification = EmailAuthVerificationResult(
            EMAIL_AUTH_RESULT_INVALID,
            transaction=current_transaction,
        )

        with patch("blueprints.auth.get_email_auth_transaction", return_value=current_transaction):
            with patch(
                "blueprints.auth.verify_email_auth_transaction",
                return_value=failed_verification,
            ):
                with patch("blueprints.auth.consume_verification_attempt_limit", return_value=(True, None)):
                    response = asyncio.run(api_verify_login_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(payload["status"], "fail")
        self.assertNotIn("login_verification_code", session)
        self.assertFalse(any(key.lower() == b"set-cookie" for key, _ in response.raw_headers))

    def test_unified_verification_dispatches_dedicated_registration_transaction(self):
        request = make_request(
            "/api/auth/verify_email_code",
            "123456",
            flow_cookie="email-transaction",
            session={},
        )
        current_transaction = transaction(flow=EMAIL_AUTH_TRANSACTION_FLOW_REGISTRATION)

        with patch("blueprints.auth.get_email_auth_transaction", return_value=current_transaction):
            with patch(
                "blueprints.auth.api_verify_registration_code",
                new=AsyncMock(return_value=jsonify({"status": "success"})),
            ) as verify_registration:
                response = asyncio.run(api_verify_email_code(request))

        self.assertEqual(response.status_code, 200)
        verify_registration.assert_awaited_once_with(request)


if __name__ == "__main__":
    unittest.main()
