import unittest
from unittest.mock import patch

from services.runtime_config import (
    get_runtime_env,
    get_session_same_site,
    get_session_secret_key,
    is_production_env,
)


# 環境変数に基づく設定値を検証するテストクラス。
# Test case class to verify setting values from environment variables.
class RuntimeConfigTestCase(unittest.TestCase):
    # FASTAPI_ENVが指定された際、その値が実行環境として適用されることを検証します。
    # Verify that get runtime env uses FASTAPI_ENV.
    def test_get_runtime_env_uses_fastapi_env(self):
        with patch.dict("os.environ", {"FASTAPI_ENV": "production"}, clear=True):
            self.assertEqual(get_runtime_env(), "production")

    # FASTAPI_ENVが未設定の場合、既定値の 'development' が返されることを検証します。
    # Verify that get runtime env defaults to 'development' when FASTAPI_ENV is unset.
    def test_get_runtime_env_defaults_to_development(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_runtime_env(), "development")

    # FASTAPI_ENVが 'production' の場合に、本番環境判定（is_production_env）がTrueを返すことを検証します。
    # Verify that is production env returns True when FASTAPI_ENV is 'production', and False otherwise.
    def test_is_production_env(self):
        # FASTAPI_ENV を production に設定して本番環境判定が True になることを検証
        # Verify that is_production_env is True when FASTAPI_ENV is set to production
        with patch.dict("os.environ", {"FASTAPI_ENV": "production"}, clear=True):
            self.assertTrue(is_production_env())

        # FASTAPI_ENV を development に設定して本番環境判定が False になることを検証
        # Verify that is_production_env is False when FASTAPI_ENV is set to development
        with patch.dict("os.environ", {"FASTAPI_ENV": "development"}, clear=True):
            self.assertFalse(is_production_env())

    # FASTAPI_SECRET_KEYが設定されている場合、その値が取得されることを検証します。
    # Verify that get session secret key returns FASTAPI_SECRET_KEY when set.
    def test_get_session_secret_key_uses_fastapi_secret(self):
        with patch.dict(
            "os.environ",
            {"FASTAPI_SECRET_KEY": "fastapi-secret"},
            clear=True,
        ):
            self.assertEqual(get_session_secret_key(), "fastapi-secret")

    # シークレットキーが指定されていない場合、Noneが返されることを検証します。
    # Verify that get session secret key returns None when both settings are missing.
    def test_get_session_secret_key_returns_none_when_missing(self):
        # シークレットキー関連の環境変数を一切設定していない状態で検証
        # Test when no secret key environment variables are set
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(get_session_secret_key())

    # 本番環境において、セッションのSameSite属性のデフォルト設定値が 'lax' になることを検証します。
    # Verify that get session same site defaults to 'lax' in production.
    def test_get_session_same_site_defaults_to_lax_in_production(self):
        # 本番環境（production）の想定でSameSite属性の初期値を確認
        # Test SameSite default value in production environment
        with patch.dict("os.environ", {"FASTAPI_ENV": "production"}, clear=True):
            self.assertEqual(get_session_same_site(), "lax")

    # 開発環境において、セッションのSameSite属性のデフォルト設定値が 'lax' になることを検証します。
    # Verify that get session same site defaults to 'lax' in development.
    def test_get_session_same_site_defaults_to_lax_in_development(self):
        # 開発環境（development）の想定でSameSite属性の初期値を確認
        # Test SameSite default value in development environment
        with patch.dict("os.environ", {"FASTAPI_ENV": "development"}, clear=True):
            self.assertEqual(get_session_same_site(), "lax")

    # 環境変数によってSameSite属性（strictなど）が明示的に上書き指定されている場合、その上書き値が適用されることを検証します。
    # Verify that get session same site uses valid override settings.
    def test_get_session_same_site_uses_valid_override(self):
        # セッションSameSite属性に strict を上書き指定して適用されることを検証
        # Verify that get_session_same_site applies valid overrides like 'strict'
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FASTAPI_SESSION_SAMESITE": "strict"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "strict")

    # 上書き指定されたSameSite属性の値が無効な文字列の場合、デフォルトの 'lax' にフォールバックすることを検証します。
    # Verify that get session same site falls back to 'lax' when override settings are invalid.
    def test_get_session_same_site_falls_back_when_override_is_invalid(self):
        # 無効な設定値（invalid）を指定した場合にデフォルト値へ戻るか検証
        # Verify that get_session_same_site falls back to 'lax' when given an invalid override value
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FASTAPI_SESSION_SAMESITE": "invalid"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "lax")

    # 本番環境以外（開発環境など）において SameSite 'none' を指定した際、セキュアな本番環境専用設定であるため適用が拒否され 'lax' になることを検証します。
    # Verify that get session same site rejects 'none' outside production and falls back to 'lax'.
    def test_get_session_same_site_rejects_none_outside_production(self):
        # 開発環境で none を上書き指定した際に拒否されることを検証
        # Verify that 'none' is rejected and fallback 'lax' is used when outside production
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "development", "FASTAPI_SESSION_SAMESITE": "none"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "lax")


if __name__ == "__main__":
    unittest.main()
