import unittest
from unittest.mock import patch

from services.google_oauth_transaction import (
    GOOGLE_OAUTH_TRANSACTION_TTL_SECONDS,
    consume_google_oauth_transaction,
    store_google_oauth_transaction,
)


class DummyRedis:
    def __init__(self):
        self.store = {}
        self.expiry = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        self.expiry[key] = ex
        return True

    def getdel(self, key):
        return self.store.pop(key, None)


class GoogleOAuthTransactionTestCase(unittest.TestCase):
    def test_transaction_is_stored_with_ttl_and_consumed_once(self):
        redis_client = DummyRedis()
        with patch(
            "services.google_oauth_transaction.get_redis_client",
            return_value=redis_client,
        ):
            self.assertTrue(
                store_google_oauth_transaction(
                    state="oauth-state",
                    code_verifier="pkce-verifier",
                    redirect_uri="https://chatcore-ai.com/google-callback",
                    next_path="/memo",
                )
            )
            self.assertEqual(
                redis_client.expiry["google_oauth_transaction:oauth-state"],
                GOOGLE_OAUTH_TRANSACTION_TTL_SECONDS,
            )

            transaction = consume_google_oauth_transaction("oauth-state")
            self.assertIsNotNone(transaction)
            self.assertEqual(transaction.code_verifier, "pkce-verifier")
            self.assertEqual(transaction.redirect_uri, "https://chatcore-ai.com/google-callback")
            self.assertEqual(transaction.next_path, "/memo")
            self.assertIsNone(consume_google_oauth_transaction("oauth-state"))

    def test_transaction_state_cannot_be_overwritten(self):
        redis_client = DummyRedis()
        with patch(
            "services.google_oauth_transaction.get_redis_client",
            return_value=redis_client,
        ):
            self.assertTrue(
                store_google_oauth_transaction(
                    state="oauth-state",
                    code_verifier="first-verifier",
                    redirect_uri="https://chatcore-ai.com/google-callback",
                    next_path=None,
                )
            )
            self.assertFalse(
                store_google_oauth_transaction(
                    state="oauth-state",
                    code_verifier="second-verifier",
                    redirect_uri="https://chatcore-ai.com/google-callback",
                    next_path=None,
                )
            )
            transaction = consume_google_oauth_transaction("oauth-state")
            self.assertEqual(transaction.code_verifier, "first-verifier")

    def test_redis_unavailable_fails_closed(self):
        with patch(
            "services.google_oauth_transaction.get_redis_client",
            return_value=None,
        ):
            self.assertFalse(
                store_google_oauth_transaction(
                    state="oauth-state",
                    code_verifier="pkce-verifier",
                    redirect_uri="https://chatcore-ai.com/google-callback",
                    next_path=None,
                )
            )
            self.assertIsNone(consume_google_oauth_transaction("oauth-state"))


if __name__ == "__main__":
    unittest.main()
