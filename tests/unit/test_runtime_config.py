import unittest
from unittest.mock import patch

from services.runtime_config import (
    get_runtime_env,
    get_session_same_site,
    get_session_secret_key,
    is_production_env,
)


class RuntimeConfigTestCase(unittest.TestCase):
    def test_get_runtime_env_prefers_fastapi_env(self):
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FLASK_ENV": "development"},
            clear=True,
        ):
            self.assertEqual(get_runtime_env(), "production")

    def test_get_runtime_env_uses_legacy_flask_env(self):
        with patch.dict("os.environ", {"FLASK_ENV": "production"}, clear=True):
            self.assertEqual(get_runtime_env(), "production")

    def test_is_production_env(self):
        with patch.dict("os.environ", {"FASTAPI_ENV": "production"}, clear=True):
            self.assertTrue(is_production_env())

        with patch.dict("os.environ", {"FASTAPI_ENV": "development"}, clear=True):
            self.assertFalse(is_production_env())

    def test_get_session_secret_key_prefers_fastapi_secret(self):
        with patch.dict(
            "os.environ",
            {
                "FASTAPI_SECRET_KEY": "fastapi-secret",
                "FLASK_SECRET_KEY": "legacy-secret",
            },
            clear=True,
        ):
            self.assertEqual(get_session_secret_key(), "fastapi-secret")

    def test_get_session_secret_key_uses_legacy_flask_secret(self):
        with patch.dict("os.environ", {"FLASK_SECRET_KEY": "legacy-secret"}, clear=True):
            self.assertEqual(get_session_secret_key(), "legacy-secret")

    def test_get_session_secret_key_returns_none_when_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(get_session_secret_key())

    def test_get_session_same_site_defaults_to_none_in_production(self):
        with patch.dict("os.environ", {"FASTAPI_ENV": "production"}, clear=True):
            self.assertEqual(get_session_same_site(), "none")

    def test_get_session_same_site_defaults_to_lax_in_development(self):
        with patch.dict("os.environ", {"FASTAPI_ENV": "development"}, clear=True):
            self.assertEqual(get_session_same_site(), "lax")

    def test_get_session_same_site_uses_valid_override(self):
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FASTAPI_SESSION_SAMESITE": "strict"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "strict")

    def test_get_session_same_site_falls_back_when_override_is_invalid(self):
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "production", "FASTAPI_SESSION_SAMESITE": "invalid"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "none")

    def test_get_session_same_site_rejects_none_outside_production(self):
        with patch.dict(
            "os.environ",
            {"FASTAPI_ENV": "development", "FASTAPI_SESSION_SAMESITE": "none"},
            clear=True,
        ):
            self.assertEqual(get_session_same_site(), "lax")


if __name__ == "__main__":
    unittest.main()
