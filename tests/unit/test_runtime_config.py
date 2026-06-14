import unittest
from unittest.mock import patch

from services.runtime_config import (
    get_runtime_env,
    get_session_same_site,
    get_session_secret_key,
    is_production_env,
)


# 日本語: RuntimeConfigTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to RuntimeConfigTestCase.
class RuntimeConfigTestCase(unittest.TestCase):
    # 日本語: test get runtime env prefers fastapi env のテスト検証を担当します。
    # English: Handle verifying test behavior for test get runtime env prefers fastapi env.
    def test_get_runtime_env_prefers_fastapi_env(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FLASK_ENV": "development"},
            clear=True,
        ):
            self.assertEqual(get_runtime_env(), "production")

    # 日本語: test get runtime env uses legacy flask env のテスト検証を担当します。
    # English: Handle verifying test behavior for test get runtime env uses legacy flask env.
    def test_get_runtime_env_uses_legacy_flask_env(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict("os.environ", {"FLASK_ENV": "production"}, clear=True):
            self.assertEqual(get_runtime_env(), "production")

    # 日本語: test is production env のテスト検証を担当します。
    # English: Handle verifying test behavior for test is production env.
    def test_is_production_env(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict("os.environ", {"FASTAPI_ENV": "production"}, clear=True):
            self.assertTrue(is_production_env())

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict("os.environ", {"FASTAPI_ENV": "development"}, clear=True):
            self.assertFalse(is_production_env())

    # 日本語: test get session secret key prefers fastapi secret のテスト検証を担当します。
    # English: Handle verifying test behavior for test get session secret key prefers fastapi secret.
    def test_get_session_secret_key_prefers_fastapi_secret(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict(
            "os.environ",
            {
                "FASTAPI_SECRET_KEY": "fastapi-secret",
                "FLASK_SECRET_KEY": "legacy-secret",
            },
            clear=True,
        ):
            self.assertEqual(get_session_secret_key(), "fastapi-secret")

    # 日本語: test get session secret key uses legacy flask secret のテスト検証を担当します。
    # English: Handle verifying test behavior for test get session secret key uses legacy flask secret.
    def test_get_session_secret_key_uses_legacy_flask_secret(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict("os.environ", {"FLASK_SECRET_KEY": "legacy-secret"}, clear=True):
            self.assertEqual(get_session_secret_key(), "legacy-secret")

    # 日本語: test get session secret key returns none when missing のテスト検証を担当します。
    # English: Handle verifying test behavior for test get session secret key returns none when missing.
    def test_get_session_secret_key_returns_none_when_missing(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(get_session_secret_key())

    # 日本語: test get session same site defaults to lax in production のテスト検証を担当します。
    # English: Handle verifying test behavior for test get session same site defaults to lax in production.
    def test_get_session_same_site_defaults_to_lax_in_production(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict("os.environ", {"FASTAPI_ENV": "production"}, clear=True):
            self.assertEqual(get_session_same_site(), "lax")

    # 日本語: test get session same site defaults to lax in development のテスト検証を担当します。
    # English: Handle verifying test behavior for test get session same site defaults to lax in development.
    def test_get_session_same_site_defaults_to_lax_in_development(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict("os.environ", {"FASTAPI_ENV": "development"}, clear=True):
            self.assertEqual(get_session_same_site(), "lax")

    # 日本語: test get session same site uses valid override のテスト検証を担当します。
    # English: Handle verifying test behavior for test get session same site uses valid override.
    def test_get_session_same_site_uses_valid_override(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FASTAPI_SESSION_SAMESITE": "strict"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "strict")

    # 日本語: test get session same site falls back when override is invalid のテスト検証を担当します。
    # English: Handle verifying test behavior for test get session same site falls back when override is invalid.
    def test_get_session_same_site_falls_back_when_override_is_invalid(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FASTAPI_SESSION_SAMESITE": "invalid"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "lax")

    # 日本語: test get session same site rejects none outside production のテスト検証を担当します。
    # English: Handle verifying test behavior for test get session same site rejects none outside production.
    def test_get_session_same_site_rejects_none_outside_production(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "development", "FASTAPI_SESSION_SAMESITE": "none"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "lax")


if __name__ == "__main__":
    unittest.main()
