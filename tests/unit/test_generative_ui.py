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

    def test_normalize_response_extracts_bare_json_artifact(self):
        raw = (
            "表示します。\n\n"
            f"{json.dumps(VALID_ARTIFACT, ensure_ascii=False)}"
        )

        normalized = normalize_response_with_artifacts(raw)

        self.assertEqual(normalized.text, "表示します。")
        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[1]["type"], "sandbox_artifact")

    def test_normalize_response_extracts_generic_json_fence_artifact(self):
        raw = (
            "表示します。\n\n"
            "```json\n"
            f"{json.dumps(VALID_ARTIFACT, ensure_ascii=False)}\n"
            "```"
        )

        normalized = normalize_response_with_artifacts(raw)

        self.assertEqual(normalized.text, "表示します。")
        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[1]["artifact"]["title"], "構成図")

    def test_normalize_response_accepts_line_continuation_jsonish_artifact(self):
        raw = r'''表示します。

{
  "version":1,
  "title":"Queue と Worker の流れ",
  "description":"Producer → Queue → Worker → Result のプロセスを可視化",
  "height":380,
  "html":"<div id='app' style='font-family:sans-serif;padding:10px;'></div>",
  "css":"#container{display:flex;flex-direction:column;align-items:center;gap:12px;}\
.box{padding:10px 20px;background:#f0f4ff;border:1px solid #3366ff;border-radius:6px;cursor:pointer;transition:background .2s;}\
#info{margin-top:16px;padding:8px 12px;background:#fafafa;border:1px solid #ddd;border-radius:4px;min-height:40px;}",
  "js":"const steps=[\
  {label:'Producer（タスク生成）',desc:'ユーザー操作や別サービスがタスクを作成し、キューへ送信します。'},\
  {label:'Queue（待機列）',desc:'FIFO でタスクを保持します。'},\
  {label:'Worker（処理実行）',desc:'Worker がタスクを取り出して処理します。'}\
];\
const app=document.getElementById('app');\
const container=document.createElement('div');container.id='container';app.appendChild(container);\
steps.forEach((s,i)=>{const b=document.createElement('div');b.className='box';b.textContent=s.label;b.dataset.idx=i;container.appendChild(b);});"
}'''

        normalized = normalize_response_with_artifacts(raw)

        self.assertEqual(normalized.text, "表示します。")
        self.assertEqual(normalized.validation_errors, [])
        self.assertIsNotNone(normalized.parts)
        artifact = normalized.parts[1]["artifact"]
        self.assertEqual(artifact["title"], "Queue と Worker の流れ")
        self.assertIn(".box", artifact["css"])
        self.assertIn("const steps", artifact["js"])
        self.assertIn("style='font-family:sans-serif;padding:10px;'", artifact["html"])

    def test_validate_artifact_rejects_network_javascript(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = "fetch('https://example.com')"

        with self.assertRaises(GenerativeUiValidationError):
            validate_artifact_payload(artifact)

    def test_validate_artifact_rejects_worker_constructor(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = "new Worker('data:,')"

        with self.assertRaises(GenerativeUiValidationError):
            validate_artifact_payload(artifact)

    def test_validate_artifact_allows_safe_html_event_handlers(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["html"] = '<button id="b" onclick="this.textContent = \'Done\'">Click</button>'

        normalized = validate_artifact_payload(artifact)

        self.assertIn("onclick", normalized["html"])

    def test_validate_artifact_removes_unsafe_html_event_handlers(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["html"] = '<button onclick="parent.postMessage({type: \'x\'}, \'*\')">Click</button>'

        normalized = validate_artifact_payload(artifact)

        self.assertNotIn("onclick", normalized["html"].lower())
        self.assertIn("Click", normalized["html"])

    def test_validate_artifact_allows_style_top_assignment(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = "document.getElementById('app').style.top = '8px';"

        normalized = validate_artifact_payload(artifact)

        self.assertIn("style.top", normalized["js"])

    def test_validate_artifact_accepts_common_aliases_and_embedded_code(self):
        artifact = {
            "name": "Alias UI",
            "body": "<style>#app{color:red;}</style><div id=\"app\"></div><script>document.getElementById('app').textContent='ok';</script>",
            "height": "1200px",
        }

        normalized = validate_artifact_payload(artifact)

        self.assertEqual(normalized["title"], "Alias UI")
        self.assertEqual(normalized["height"], 900)
        self.assertNotIn("<script", normalized["html"].lower())
        self.assertIn("#app{color:red;}", normalized["css"])
        self.assertIn("textContent='ok'", normalized["js"])

    def test_normalize_response_hides_validation_failure_note_from_user_text(self):
        raw = (
            "短い説明です。\n\n"
            "```chatcore-artifact\n"
            '{"version":1,"title":"Bad","html":"<div></div>","css":"","js":"fetch(\'https://example.com\')"}\n'
            "```"
        )

        normalized = normalize_response_with_artifacts(raw)

        self.assertEqual(normalized.text, "短い説明です。")
        self.assertIsNone(normalized.parts)
        self.assertNotIn("安全検証", normalized.text)
        self.assertTrue(normalized.validation_errors)

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
