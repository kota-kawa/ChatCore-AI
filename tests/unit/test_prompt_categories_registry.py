import unittest

from pydantic import ValidationError

from services.prompt_categories import (
    CATEGORY_OTHER,
    CATEGORY_UNSET,
    LEGACY_CATEGORY_ALIASES,
    PROMPT_CATEGORIES,
    category_keys_matching,
    category_label,
    is_valid_category,
    normalize_category,
)
from services.request_models import PromptUpdateRequest, SharedPromptCreateRequest


# カテゴリレジストリ (services/prompt_categories.py) のユニットテスト。
# Unit tests for the category registry (services/prompt_categories.py).
class PromptCategoriesRegistryTestCase(unittest.TestCase):
    # 正準キーはそのまま通り、ラベルが解決できることを検証します。
    # Verify canonical keys pass through and resolve to a display label.
    def test_canonical_keys_normalize_to_themselves(self):
        for key, category in PROMPT_CATEGORIES.items():
            self.assertEqual(normalize_category(key), key)
            self.assertEqual(category_label(key), category.label)
            self.assertTrue(is_valid_category(key))

    # 旧日本語カテゴリがすべて正準キー（または未設定）へ解決されることを検証します。
    # Verify every legacy Japanese category resolves to a canonical key (or unset).
    def test_legacy_aliases_resolve_to_canonical_keys(self):
        for legacy, expected in LEGACY_CATEGORY_ALIASES.items():
            self.assertEqual(normalize_category(legacy), expected)
            if expected:
                self.assertIn(expected, PROMPT_CATEGORIES)

    # 空値は未設定、未知の値は None（=バリデーションエラー）になることを検証します。
    # Verify empty means unset while unknown values are rejected with None.
    def test_empty_is_unset_and_unknown_is_rejected(self):
        for empty in ("", "   ", None):
            self.assertEqual(normalize_category(empty), CATEGORY_UNSET)
            self.assertTrue(is_valid_category(empty))
        self.assertIsNone(normalize_category("架空のカテゴリ"))
        self.assertFalse(is_valid_category("架空のカテゴリ"))
        self.assertEqual(category_label("架空のカテゴリ"), "")

    # 「その他」はフィルタUI上の慣例どおり末尾に置かれることを検証します。
    # Verify the catch-all category stays last, as the filter UI expects.
    def test_other_category_is_last(self):
        self.assertEqual(list(PROMPT_CATEGORIES)[-1], CATEGORY_OTHER)

    # 日本語ラベル・キーの部分一致でカテゴリキーを引けることを検証します。
    # Verify categories are searchable by a substring of their label or key.
    def test_category_keys_matching_resolves_labels_and_keys(self):
        self.assertEqual(category_keys_matching("文章"), ["writing"])
        self.assertEqual(category_keys_matching("coding"), ["coding"])
        # 複数のラベルが共通の部分文字列を含む場合は、レジストリ順で全件返る
        # When several labels share a substring, every match is returned in registry order
        self.assertEqual(category_keys_matching("学"), ["learning", "language"])
        self.assertEqual(category_keys_matching(""), [])
        self.assertEqual(category_keys_matching("該当なし"), [])


# カテゴリのリクエストバリデーションのユニットテスト。
# Unit tests for category validation on request payloads.
class PromptCategoryValidationTestCase(unittest.TestCase):
    # 投稿リクエストで旧日本語カテゴリが正準キーへ正規化されることを検証します。
    # Verify a legacy Japanese category is normalized to its canonical key on create.
    def test_create_request_normalizes_legacy_category(self):
        payload = SharedPromptCreateRequest(title="t", category="仕事", content="c")
        self.assertEqual(payload.category, "business")

    # 投稿リクエストでカテゴリ未指定が許容されることを検証します。
    # Verify an unset category is accepted on create.
    def test_create_request_allows_unset_category(self):
        payload = SharedPromptCreateRequest(title="t", category="", content="c")
        self.assertEqual(payload.category, CATEGORY_UNSET)

    # レジストリにないカテゴリが投稿リクエストで拒否されることを検証します。
    # Verify a category outside the registry is rejected on create.
    def test_create_request_rejects_unknown_category(self):
        with self.assertRaises(ValidationError):
            SharedPromptCreateRequest(title="t", category="架空のカテゴリ", content="c")

    # 更新リクエストでカテゴリが正規化され、未設定・未知が拒否されることを検証します。
    # Verify update normalizes the category and rejects both unset and unknown values.
    def test_update_request_normalizes_and_requires_category(self):
        payload = PromptUpdateRequest(title="t", category="勉強", content="c")
        self.assertEqual(payload.category, "learning")

        with self.assertRaises(ValidationError):
            PromptUpdateRequest(title="t", category="未選択", content="c")
        with self.assertRaises(ValidationError):
            PromptUpdateRequest(title="t", category="架空のカテゴリ", content="c")


if __name__ == "__main__":
    unittest.main()
