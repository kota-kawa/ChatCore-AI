import unittest
from unittest.mock import patch

from services.runtime_config import (
    get_runtime_env,
    get_session_same_site,
    get_session_secret_key,
    is_production_env,
)


# 環境変数に基づく設定値や、旧環境変数（Flask等）からの移行互換性を検証するテストクラス。
# Test case class to verify setting values from environment variables and backward compatibility.
class RuntimeConfigTestCase(unittest.TestCase):
    # FASTAPI_ENVとFLASK_ENVの両方が指定された際、優先度の高いFASTAPI_ENVの値が優先して適用されることを検証します。
    # Verify that get runtime env prefers fastapi env.
    def test_get_runtime_env_prefers_fastapi_env(self):
        # 両方の環境変数が設定されている状態で検証
        # Test behavior when both environment variables are set
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FLASK_ENV": "development"},
            clear=True,
        ):
            self.assertEqual(get_runtime_env(), "production")

    # 旧設定であるFLASK_ENVのみが指定されている場合、下位互換性のためその値が適用されることを検証します。
    # Verify that get runtime env falls back to use the legacy flask env value.
    def test_get_runtime_env_uses_legacy_flask_env(self):
        # レガシーな環境変数のみが設定されている状態で検証
        # Test behavior when only the legacy environment variable is set
        with patch.dict("os.environ", {"FLASK_ENV": "production"}, clear=True):
            self.assertEqual(get_runtime_env(), "production")

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

    # 新旧両方のシークレットキーが設定されている場合、優先度の高いFASTAPI_SECRET_KEYが取得されることを検証します。
    # Verify that get session secret key prefers fastapi secret key over flask secret key.
    def test_get_session_secret_key_prefers_fastapi_secret(self):
        # 両方のシークレットキーが環境変数に設定された状態で検証
        # Test when both secret key environment variables are set
        with patch.dict(
            "os.environ",
            {
                "FASTAPI_SECRET_KEY": "fastapi-secret",
                "FLASK_SECRET_KEY": "legacy-secret",
            },
            clear=True,
        ):
            self.assertEqual(get_session_secret_key(), "fastapi-secret")

    # 旧設定であるFLASK_SECRET_KEYのみが指定されている場合、下位互換性のためにその値が適用されることを検証します。
    # Verify that get session secret key uses legacy flask secret key when the new one is missing.
    def test_get_session_secret_key_uses_legacy_flask_secret(self):
        # レガシーなシークレットキーのみが環境変数に設定された状態で検証
        # Test when only the legacy secret key environment variable is set
        with patch.dict("os.environ", {"FLASK_SECRET_KEY": "legacy-secret"}, clear=True):
            self.assertEqual(get_session_secret_key(), "legacy-secret")

    # どちらのシークレットキーも指定されていない場合、Noneが返されることを検証します。
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
