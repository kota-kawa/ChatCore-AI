import unittest

from services.i18n import (
    get_current_locale,
    normalize_locale,
    parse_accept_language,
    reset_current_locale,
    set_current_locale,
    translate,
    translate_text,
)


class I18nTestCase(unittest.TestCase):
    def test_normalize_locale_accepts_region_tags(self):
        self.assertEqual(normalize_locale("en-US"), "en")
        self.assertEqual(normalize_locale("ja_JP"), "ja")
        self.assertIsNone(normalize_locale("fr-FR"))

    def test_accept_language_honors_quality(self):
        self.assertEqual(parse_accept_language("ja;q=0.5, en-US;q=0.9"), "en")
        self.assertEqual(parse_accept_language("fr-FR, *;q=0.5"), "ja")

    def test_context_locale_controls_translation(self):
        token = set_current_locale("en")
        try:
            self.assertEqual(get_current_locale(), "en")
            self.assertEqual(translate("common.login_required"), "Login is required.")
            self.assertEqual(translate_text("内部エラーが発生しました。"), "An internal server error occurred.")
            self.assertEqual(translate_text("ユーザーが書いた内容"), "ユーザーが書いた内容")
        finally:
            reset_current_locale(token)


if __name__ == "__main__":
    unittest.main()
