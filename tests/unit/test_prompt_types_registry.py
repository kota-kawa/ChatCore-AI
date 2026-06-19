import unittest

from services.prompt_types import (
    CONTENT_FORMAT_SKILL,
    MEDIA_TYPE_IMAGE,
    derive_legacy_prompt_type,
    legacy_prompt_type_to_axes,
    media_allows_attachment,
    normalize_content_format,
    normalize_media_type,
    requires_content,
    sanitize_attributes,
    serialize_axes,
    validate_attributes,
)


# 2軸モデルのレジストリ (services/prompt_types.py) のユニットテスト。
# Unit tests for the two-axis model registry (services/prompt_types.py).
class PromptTypesRegistryTestCase(unittest.TestCase):
    # 旧 prompt_type と2軸の相互変換が一貫していることを検証します。
    # Verify that the legacy <-> two-axis mapping is consistent in both directions.
    def test_legacy_prompt_type_round_trip(self):
        for legacy in ("text", "image", "skill"):
            content_format, media_type = legacy_prompt_type_to_axes(legacy)
            self.assertEqual(derive_legacy_prompt_type(content_format, media_type), legacy)

    # 未知の軸値が既定値へフォールバックすることを検証します。
    # Verify that unknown axis values fall back to defaults.
    def test_normalization_falls_back_to_defaults(self):
        self.assertEqual(normalize_content_format("nope"), "prompt")
        self.assertEqual(normalize_media_type("nope"), "text")
        # 旧エイリアスの吸収
        # Resolve legacy aliases.
        self.assertEqual(normalize_content_format("claude_skill"), CONTENT_FORMAT_SKILL)
        self.assertEqual(normalize_media_type("image_generation"), MEDIA_TYPE_IMAGE)

    # skill フォーマットの必須属性検証が機能することを検証します。
    # Verify required-attribute validation for the skill format.
    def test_validate_attributes_requires_skill_markdown(self):
        errors = validate_attributes(CONTENT_FORMAT_SKILL, {"skill_markdown": ""})
        self.assertTrue(errors)
        ok = validate_attributes(CONTENT_FORMAT_SKILL, {"skill_markdown": "# x"})
        self.assertEqual(ok, [])

    # 宣言外のキーが sanitize で破棄され、宣言済みキーが文字列化されることを検証します。
    # Verify that undeclared keys are dropped and declared keys are stringified by sanitize.
    def test_sanitize_attributes_keeps_only_declared_keys(self):
        cleaned = sanitize_attributes(
            CONTENT_FORMAT_SKILL,
            {"skill_markdown": "# x", "junk": "drop", "skill_python_script": None},
        )
        self.assertEqual(set(cleaned), {"skill_markdown", "skill_python_script"})
        self.assertEqual(cleaned["skill_python_script"], "")
        self.assertNotIn("junk", cleaned)

    # prompt フォーマットは content 必須、skill フォーマットは不要であることを検証します。
    # Verify that the prompt format requires content while the skill format does not.
    def test_requires_content(self):
        self.assertTrue(requires_content("prompt"))
        self.assertFalse(requires_content("skill"))

    # 画像メディアは添付を許可し、テキストメディアは許可しないことを検証します。
    # Verify that the image media allows attachments while text does not.
    def test_media_allows_attachment(self):
        self.assertTrue(media_allows_attachment("image"))
        self.assertFalse(media_allows_attachment("text"))

    # serialize_axes が正準フィールドと後方互換の派生フィールドを返すことを検証します。
    # Verify serialize_axes returns canonical fields plus derived legacy fields.
    def test_serialize_axes_builds_derived_fields(self):
        row = {
            "content_format": "skill",
            "media_type": "text",
            "attributes": {"skill_markdown": "# x", "skill_python_script": "print(1)"},
            "attachments": [],
        }
        out = serialize_axes(row)
        self.assertEqual(out["prompt_type"], "skill")
        self.assertEqual(out["skill_markdown"], "# x")
        self.assertEqual(out["skill_python_script"], "print(1)")
        self.assertIsNone(out["reference_image_url"])

        image_row = {
            "content_format": "prompt",
            "media_type": "image",
            "attributes": {},
            "attachments": [
                {"url": "/static/uploads/prompt_share/x.png", "role": "reference", "media_type": "image/png"}
            ],
        }
        image_out = serialize_axes(image_row)
        self.assertEqual(image_out["prompt_type"], "image")
        self.assertEqual(image_out["reference_image_url"], "/static/uploads/prompt_share/x.png")


if __name__ == "__main__":
    unittest.main()
