import re
import unittest

from services.i18n import (
    build_response_language_policy,
    get_current_locale,
    infer_response_language,
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

    # 日本語: 応答言語ポリシーが入力言語優先であり、保存ロケールは最終手段であることを検証します。
    # English: Verify the policy follows the input language and treats the saved locale as a last resort.
    def test_response_language_policy_prefers_input_language(self):
        policy = build_response_language_policy("ja")

        self.assertIn("language of the user's input text", policy)
        self.assertIn("An explicit language request from the user takes priority", policy)
        self.assertIn("saved interface language (Japanese)", policy)
        self.assertIn("Do not translate user-authored content", policy)

    # 日本語: 混在言語入力の判断順序（依頼部分の言語 → 分量比 → 保存ロケール）を検証します。
    # English: Verify the mixed-language order: request language, then share of text, then saved locale.
    def test_response_language_policy_resolves_mixed_language_input(self):
        policy = build_response_language_policy("en")

        request_rule = policy.index("the part that states the user's request or instruction")
        share_rule = policy.index("larger share")
        fallback_rule = policy.index("saved interface language (English)")

        self.assertLess(request_rule, share_rule)
        self.assertLess(share_rule, fallback_rule)
        self.assertIn("quoted text, pasted logs, code, error messages", policy)
        self.assertIn("Keep one language throughout a single reply", policy)

    # 日本語: ポリシー文自体が英語で書かれていることを検証します。
    # English: Verify the policy text itself is written in English.
    def test_response_language_policy_is_written_in_english(self):
        for locale in ("ja", "en", None):
            with self.subTest(locale=locale):
                self.assertFalse(
                    re.search(r"[぀-ヿ一-鿿]", build_response_language_policy(locale))
                )

    # 日本語: 長い貼り付け文より依頼部分の言語を非LLMフォールバックでも優先することを検証します。
    # English: Verify non-LLM fallbacks prioritize the request language over a long pasted body.
    def test_infer_response_language_prefers_request_portion(self):
        text = "以下の内容を要約して\n" + ("This is a long pasted English document. " * 50)

        self.assertEqual(infer_response_language(text, "en"), "ja")


if __name__ == "__main__":
    unittest.main()
