# 日本語: 環境変数読み取りの共通ヘルパーが、統合前の各実装と同じ既定値挙動を保つことを検証します。
# English: Verifies the shared environment-variable helpers keep the fallback behaviour of the implementations they replaced.

import os
import unittest
from unittest.mock import patch

from services import env_settings


class EnvTextTestCase(unittest.TestCase):
    def test_returns_default_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(env_settings.env_text("MISSING"))
            self.assertEqual(env_settings.env_text("MISSING", "fallback"), "fallback")

    def test_treats_empty_string_as_unset(self) -> None:
        with patch.dict(os.environ, {"EMPTY": ""}, clear=True):
            self.assertEqual(env_settings.env_text("EMPTY", "fallback"), "fallback")

    def test_returns_configured_value(self) -> None:
        with patch.dict(os.environ, {"NAME": "value"}, clear=True):
            self.assertEqual(env_settings.env_text("NAME", "fallback"), "value")


class EnvBoolTestCase(unittest.TestCase):
    def test_accepts_every_true_spelling(self) -> None:
        for raw in ("1", "true", "TRUE", " yes ", "On"):
            with self.subTest(raw=raw), patch.dict(os.environ, {"FLAG": raw}, clear=True):
                self.assertTrue(env_settings.env_bool("FLAG"))

    def test_rejects_other_values(self) -> None:
        for raw in ("0", "false", "no", "off", "maybe"):
            with self.subTest(raw=raw), patch.dict(os.environ, {"FLAG": raw}, clear=True):
                self.assertFalse(env_settings.env_bool("FLAG", default=True))

    def test_returns_default_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(env_settings.env_bool("FLAG", default=True))
            self.assertFalse(env_settings.env_bool("FLAG"))


class EnvIntTestCase(unittest.TestCase):
    def test_returns_default_when_unset_or_unparsable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_settings.env_int("SIZE", 7), 7)
        with patch.dict(os.environ, {"SIZE": "abc"}, clear=True):
            self.assertEqual(env_settings.env_int("SIZE", 7), 7)
        with patch.dict(os.environ, {"SIZE": ""}, clear=True):
            self.assertEqual(env_settings.env_int("SIZE", 7), 7)

    def test_rejects_values_below_minimum(self) -> None:
        with patch.dict(os.environ, {"SIZE": "0"}, clear=True):
            self.assertEqual(env_settings.env_int("SIZE", 7), 7)
        with patch.dict(os.environ, {"SIZE": "-3"}, clear=True):
            self.assertEqual(env_settings.env_int("SIZE", 7), 7)

    def test_allows_zero_when_minimum_is_zero(self) -> None:
        with patch.dict(os.environ, {"RETRIES": "0"}, clear=True):
            self.assertEqual(env_settings.env_int("RETRIES", 3, minimum=0), 0)
        with patch.dict(os.environ, {"RETRIES": "-1"}, clear=True):
            self.assertEqual(env_settings.env_int("RETRIES", 3, minimum=0), 3)

    def test_accepts_any_integer_when_minimum_is_disabled(self) -> None:
        with patch.dict(os.environ, {"OFFSET": "-5"}, clear=True):
            self.assertEqual(env_settings.env_int("OFFSET", 0, minimum=None), -5)

    def test_ignores_surrounding_whitespace(self) -> None:
        with patch.dict(os.environ, {"SIZE": " 12 "}, clear=True):
            self.assertEqual(env_settings.env_int("SIZE", 7), 12)

    def test_warns_only_when_requested(self) -> None:
        with patch.dict(os.environ, {"SIZE": "abc"}, clear=True):
            with self.assertLogs(env_settings.logger, level="WARNING") as captured:
                env_settings.env_int("SIZE", 7, warn_on_invalid=True)
            self.assertIn("Invalid SIZE value", captured.output[0])

        with patch.dict(os.environ, {"SIZE": "abc"}, clear=True):
            with self.assertLogs(env_settings.logger, level="DEBUG") as captured:
                env_settings.env_int("SIZE", 7)
            self.assertTrue(all(record.startswith("DEBUG") for record in captured.output))


class EnvIntInRangeTestCase(unittest.TestCase):
    def test_clamps_instead_of_falling_back(self) -> None:
        with patch.dict(os.environ, {"COUNT": "500"}, clear=True):
            self.assertEqual(env_settings.env_int_in_range("COUNT", 5, minimum=1, maximum=100), 100)
        with patch.dict(os.environ, {"COUNT": "-4"}, clear=True):
            self.assertEqual(env_settings.env_int_in_range("COUNT", 5, minimum=1, maximum=100), 1)

    def test_clamps_lower_bound_without_maximum(self) -> None:
        with patch.dict(os.environ, {"COUNT": "-4"}, clear=True):
            self.assertEqual(env_settings.env_int_in_range("COUNT", 5, minimum=0), 0)
        with patch.dict(os.environ, {"COUNT": "9000"}, clear=True):
            self.assertEqual(env_settings.env_int_in_range("COUNT", 5, minimum=0), 9000)

    def test_returns_default_when_unset_or_unparsable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_settings.env_int_in_range("COUNT", 5, minimum=1, maximum=100), 5)
        with patch.dict(os.environ, {"COUNT": "abc"}, clear=True):
            self.assertEqual(env_settings.env_int_in_range("COUNT", 5, minimum=1, maximum=100), 5)


class EnvFloatTestCase(unittest.TestCase):
    def test_returns_default_when_unset_or_unparsable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertAlmostEqual(env_settings.env_float("TIMEOUT", 1.5), 1.5)
        with patch.dict(os.environ, {"TIMEOUT": "abc"}, clear=True):
            self.assertAlmostEqual(env_settings.env_float("TIMEOUT", 1.5), 1.5)

    def test_rejects_non_positive_values_by_default(self) -> None:
        for raw in ("0", "0.0", "-2.5"):
            with self.subTest(raw=raw), patch.dict(os.environ, {"TIMEOUT": raw}, clear=True):
                self.assertAlmostEqual(env_settings.env_float("TIMEOUT", 1.5), 1.5)

    def test_allows_zero_when_minimum_is_inclusive(self) -> None:
        with patch.dict(os.environ, {"DISTANCE": "0"}, clear=True):
            self.assertAlmostEqual(env_settings.env_float("DISTANCE", 1.5, minimum_inclusive=True), 0.0)

    def test_returns_configured_value(self) -> None:
        with patch.dict(os.environ, {"TIMEOUT": " 2.25 "}, clear=True):
            self.assertAlmostEqual(env_settings.env_float("TIMEOUT", 1.5), 2.25)


if __name__ == "__main__":
    unittest.main()
