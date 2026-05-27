import json
import unittest

from services.generative_ui import (
    GenerativeUiValidationError,
    decode_message_parts,
    normalize_response_with_artifacts,
    validate_artifact_payload,
)


VALID_ARTIFACT = {
    "version": 1,
    "title": "構成図",
    "description": "クリックできる簡易図解",
    "height": 360,
    "html": '<div id="app"></div>',
    "css": "#app{padding:16px;border-radius:8px;background:#f8fafc;}",
    "js": "document.getElementById('app').textContent = 'ready';",
}


class GenerativeUiTestCase(unittest.TestCase):
    def test_normalize_response_extracts_valid_artifact_block(self):
        raw = (
            "以下の図で整理しました。\n\n"
            "```chatcore-artifact\n"
            f"{json.dumps(VALID_ARTIFACT, ensure_ascii=False)}\n"
            "```"
        )

        normalized = normalize_response_with_artifacts(raw)

        self.assertEqual(normalized.text, "以下の図で整理しました。")
        self.assertEqual(normalized.validation_errors, [])
        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[0], {"type": "text", "text": "以下の図で整理しました。"})
        self.assertEqual(normalized.parts[1]["type"], "sandbox_artifact")
        self.assertEqual(normalized.parts[1]["artifact"]["title"], "構成図")

    def test_normalize_response_keeps_plain_text_unchanged(self):
        normalized = normalize_response_with_artifacts("通常の回答です。")

        self.assertEqual(normalized.text, "通常の回答です。")
        self.assertIsNone(normalized.parts)

    def test_validate_artifact_rejects_network_javascript(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = "fetch('https://example.com')"

        with self.assertRaises(GenerativeUiValidationError):
            validate_artifact_payload(artifact)

    def test_validate_artifact_rejects_html_event_handlers(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["html"] = '<button onclick="alert(1)">Click</button>'

        with self.assertRaises(GenerativeUiValidationError):
            validate_artifact_payload(artifact)

    def test_decode_message_parts_drops_invalid_artifacts(self):
        parts = [
            {"type": "text", "text": "hello"},
            {
                "type": "sandbox_artifact",
                "artifact": {
                    **VALID_ARTIFACT,
                    "js": "window.top.location = 'https://example.com'",
                },
            },
        ]

        self.assertEqual(decode_message_parts(parts), [{"type": "text", "text": "hello"}])


if __name__ == "__main__":
    unittest.main()
