import unittest
from unittest.mock import patch

from services.runtime_config import (
    get_runtime_env,
    get_session_same_site,
    get_session_secret_key,
    is_production_env,
)


# 日本語: Runtime Configの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Runtime Config.
class RuntimeConfigTestCase(unittest.TestCase):
    # 日本語: getランタイムenvprefersfastapienvことを検証します。
    # English: Verify that get runtime env prefers fastapi env.
    def test_get_runtime_env_prefers_fastapi_env(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FLASK_ENV": "development"},
            clear=True,
        ):
            self.assertEqual(get_runtime_env(), "production")

    # 日本語: getランタイムenvuseslegacyflaskenvことを検証します。
    # English: Verify that get runtime env uses legacy flask env.
    def test_get_runtime_env_uses_legacy_flask_env(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict("os.environ", {"FLASK_ENV": "production"}, clear=True):
            self.assertEqual(get_runtime_env(), "production")

    # 日本語: がproductionenvことを検証します。
    # English: Verify that is production env.
    def test_is_production_env(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict("os.environ", {"FASTAPI_ENV": "production"}, clear=True):
            self.assertTrue(is_production_env())

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict("os.environ", {"FASTAPI_ENV": "development"}, clear=True):
            self.assertFalse(is_production_env())

    # 日本語: getセッションsecretkeyprefersfastapisecretことを検証します。
    # English: Verify that get session secret key prefers fastapi secret.
    def test_get_session_secret_key_prefers_fastapi_secret(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(
            "os.environ",
            {
                "FASTAPI_SECRET_KEY": "fastapi-secret",
                "FLASK_SECRET_KEY": "legacy-secret",
            },
            clear=True,
        ):
            self.assertEqual(get_session_secret_key(), "fastapi-secret")

    # 日本語: getセッションsecretkeyuseslegacyflasksecretことを検証します。
    # English: Verify that get session secret key uses legacy flask secret.
    def test_get_session_secret_key_uses_legacy_flask_secret(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict("os.environ", {"FLASK_SECRET_KEY": "legacy-secret"}, clear=True):
            self.assertEqual(get_session_secret_key(), "legacy-secret")

    # 日本語: missingのとき、getセッションsecretkey返却するnoneことを検証します。
    # English: Verify that get session secret key returns none when missing.
    def test_get_session_secret_key_returns_none_when_missing(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(get_session_secret_key())

    # 日本語: laxへ、production内の、getセッションsamesitedefaultsことを検証します。
    # English: Verify that get session same site defaults to lax in production.
    def test_get_session_same_site_defaults_to_lax_in_production(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict("os.environ", {"FASTAPI_ENV": "production"}, clear=True):
            self.assertEqual(get_session_same_site(), "lax")

    # 日本語: laxへ、development内の、getセッションsamesitedefaultsことを検証します。
    # English: Verify that get session same site defaults to lax in development.
    def test_get_session_same_site_defaults_to_lax_in_development(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict("os.environ", {"FASTAPI_ENV": "development"}, clear=True):
            self.assertEqual(get_session_same_site(), "lax")

    # 日本語: getセッションsamesiteuses有効なoverrideことを検証します。
    # English: Verify that get session same site uses valid override.
    def test_get_session_same_site_uses_valid_override(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FASTAPI_SESSION_SAMESITE": "strict"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "strict")

    # 日本語: overrideが無効なのとき、getセッションsamesitefallsことを検証します。
    # English: Verify that get session same site falls back when override is invalid.
    def test_get_session_same_site_falls_back_when_override_is_invalid(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FASTAPI_SESSION_SAMESITE": "invalid"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "lax")

    # 日本語: getセッションsamesite拒否するnoneoutsideproductionことを検証します。
    # English: Verify that get session same site rejects none outside production.
    def test_get_session_same_site_rejects_none_outside_production(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "development", "FASTAPI_SESSION_SAMESITE": "none"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "lax")


if __name__ == "__main__":
    unittest.main()
