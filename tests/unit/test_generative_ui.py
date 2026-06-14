import json
import re
import unittest

from blueprints.chat.messages import BASE_SYSTEM_PROMPT
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


# 日本語: Generative Uiの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Generative Ui.
class GenerativeUiTestCase(unittest.TestCase):
    # 日本語: normalizeレスポンスextracts有効なartifactblockことを検証します。
    # English: Verify that normalize response extracts valid artifact block.
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

    # 日本語: normalizeレスポンス保持するplaintextunchangedことを検証します。
    # English: Verify that normalize response keeps plain text unchanged.
    def test_normalize_response_keeps_plain_text_unchanged(self):
        normalized = normalize_response_with_artifacts("通常の回答です。")

        self.assertEqual(normalized.text, "通常の回答です。")
        self.assertIsNone(normalized.parts)

    # 日本語: normalizeレスポンスextractsbarejsonartifactことを検証します。
    # English: Verify that normalize response extracts bare json artifact.
    def test_normalize_response_extracts_bare_json_artifact(self):
        raw = (
            "表示します。\n\n"
            f"{json.dumps(VALID_ARTIFACT, ensure_ascii=False)}"
        )

        normalized = normalize_response_with_artifacts(raw)

        self.assertEqual(normalized.text, "表示します。")
        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[1]["type"], "sandbox_artifact")

    # 日本語: normalizeレスポンスextractsgenericjsonfenceartifactことを検証します。
    # English: Verify that normalize response extracts generic json fence artifact.
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

    # 日本語: normalizeレスポンスextractssplitsourceコードブロックすることを検証します。
    # English: Verify that normalize response extracts split source code blocks.
    def test_normalize_response_extracts_split_source_code_blocks(self):
        raw = """表示します。

```html
<div id="app"></div>
```

```css
#app{padding:12px;background:#eef2ff;}
```

```js
document.getElementById('app').textContent = 'ready';
```
"""

        normalized = normalize_response_with_artifacts(raw)

        self.assertEqual(normalized.text, "表示します。")
        self.assertEqual(normalized.validation_errors, [])
        self.assertIsNotNone(normalized.parts)
        artifact = normalized.parts[1]["artifact"]
        self.assertIn('<div id="app"></div>', artifact["html"])
        self.assertIn("#app{padding", artifact["css"])
        self.assertIn("textContent", artifact["js"])

    # 日本語: およびcompact、ベースプロンプトfewshotartifactsが有効なことを検証します。
    # English: Verify that base prompt few shot artifacts are valid and compact.
    def test_base_prompt_few_shot_artifacts_are_valid_and_compact(self):
        artifact_blocks = re.findall(
            r"```chatcore-artifact\s*(\{[\s\S]*?\})\s*```",
            BASE_SYSTEM_PROMPT,
        )

        self.assertGreaterEqual(len(artifact_blocks), 3)
        # 日本語: 各対象データを順に処理し、検証を行います。
        # English: Process each target item in sequence to perform validation.
        for raw_payload in artifact_blocks:
            payload = json.loads(raw_payload)
            artifact = validate_artifact_payload(payload)

            self.assertRegex(artifact["html"], r"id=[\"']app[\"']")
            self.assertLessEqual(
                len(artifact["html"]) + len(artifact["css"]) + len(artifact["js"]),
                8000,
            )
            self.assertLessEqual(artifact.get("height", 0), 720)

    # 日本語: shortdisplayintentに対して、normalizeレスポンス作成するfallbackことを検証します。
    # English: Verify that normalize response creates fallback for short display intent.
    def test_normalize_response_creates_fallback_for_short_display_intent(self):
        normalized = normalize_response_with_artifacts("表示します。")

        self.assertEqual(normalized.text, "表示します。")
        self.assertIsNotNone(normalized.parts)
        artifact = normalized.parts[1]["artifact"]
        self.assertEqual(artifact["title"], "表示します。")
        self.assertIn("fallback-ui", artifact["html"])

    # 日本語: normalizeレスポンスacceptslinecontinuationjsonishartifactことを検証します。
    # English: Verify that normalize response accepts line continuation jsonish artifact.
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

    # 日本語: validateartifact拒否するnetworkjavascriptことを検証します。
    # English: Verify that validate artifact rejects network javascript.
    def test_validate_artifact_rejects_network_javascript(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = "fetch('https://example.com')"

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with self.assertRaises(GenerativeUiValidationError):
            validate_artifact_payload(artifact)

    # 日本語: validateartifact拒否するworkerconstructorことを検証します。
    # English: Verify that validate artifact rejects worker constructor.
    def test_validate_artifact_rejects_worker_constructor(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = "new Worker('data:,')"

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with self.assertRaises(GenerativeUiValidationError):
            validate_artifact_payload(artifact)

    # 日本語: validateartifact許可するsafehtmleventhandlersことを検証します。
    # English: Verify that validate artifact allows safe html event handlers.
    def test_validate_artifact_allows_safe_html_event_handlers(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["html"] = '<button id="b" onclick="this.textContent = \'Done\'">Click</button>'

        normalized = validate_artifact_payload(artifact)

        self.assertIn("onclick", normalized["html"])

    # 日本語: validateartifactremovesunsafehtmleventhandlersことを検証します。
    # English: Verify that validate artifact removes unsafe html event handlers.
    def test_validate_artifact_removes_unsafe_html_event_handlers(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["html"] = '<button onclick="parent.postMessage({type: \'x\'}, \'*\')">Click</button>'

        normalized = validate_artifact_payload(artifact)

        self.assertNotIn("onclick", normalized["html"].lower())
        self.assertIn("Click", normalized["html"])

    # 日本語: validateartifact許可するstyletopassignmentことを検証します。
    # English: Verify that validate artifact allows style top assignment.
    def test_validate_artifact_allows_style_top_assignment(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = "document.getElementById('app').style.top = '8px';"

        normalized = validate_artifact_payload(artifact)

        self.assertIn("style.top", normalized["js"])

    # 日本語: およびembeddedコード、validateartifactacceptscommonaliasesことを検証します。
    # English: Verify that validate artifact accepts common aliases and embedded code.
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

    # 日本語: artifact検証失敗するのとき、normalizeレスポンスusesfallbackことを検証します。
    # English: Verify that normalize response uses fallback when artifact validation fails.
    def test_normalize_response_uses_fallback_when_artifact_validation_fails(self):
        raw = (
            "短い説明です。\n\n"
            "```chatcore-artifact\n"
            '{"version":1,"title":"Bad","html":"<div></div>","css":"","js":"fetch(\'https://example.com\')"}\n'
            "```"
        )

        normalized = normalize_response_with_artifacts(raw)

        self.assertEqual(normalized.text, "短い説明です。")
        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[1]["type"], "sandbox_artifact")
        self.assertIn("fallback-ui", normalized.parts[1]["artifact"]["html"])
        self.assertNotIn("安全検証", normalized.text)
        self.assertTrue(normalized.validation_errors)

    # 日本語: 空htmlに対して、validateartifactaddsデフォルトapprootことを検証します。
    # English: Verify that validate artifact adds default app root for empty html.
    def test_validate_artifact_adds_default_app_root_for_empty_html(self):
        artifact = dict(VALID_ARTIFACT)
        artifact["html"] = ""
        artifact["js"] = "document.getElementById('app').textContent = 'ready';"

        normalized = validate_artifact_payload(artifact)

        self.assertIn('id="app"', normalized["html"])

    # 日本語: recoverstruncatedartifactcutoffinsidestringことを検証します。
    # English: Verify that recovers truncated artifact cut off inside string.
    def test_recovers_truncated_artifact_cut_off_inside_string(self):
        raw = (
            "ツリーを表示します。\n\n"
            "```chatcore-artifact\n"
            '{"version":1,"title":"中央省庁ツリー","description":"主要省庁","height":520,'
            "\"html\":\"<div id='app'><ul class='tree'><li>"
            "<button class='tog'>復興庁</button><ul class='sub'><li>"
        )

        normalized = normalize_response_with_artifacts(raw, recover_truncated=True)

        self.assertEqual(normalized.text, "ツリーを表示します。")
        self.assertEqual(normalized.validation_errors, [])
        self.assertIsNotNone(normalized.parts)
        artifact = normalized.parts[1]["artifact"]
        self.assertEqual(artifact["title"], "中央省庁ツリー")
        self.assertIn("復興庁", artifact["html"])
        self.assertNotIn("fallback-ui", artifact["html"])
        # The broken JSON must never leak into the visible text.
        self.assertNotIn("chatcore-artifact", normalized.text)
        self.assertNotIn('"version"', normalized.text)

    # 日本語: recoverscompleteartifactmissingclosingfenceことを検証します。
    # English: Verify that recovers complete artifact missing closing fence.
    def test_recovers_complete_artifact_missing_closing_fence(self):
        raw = (
            "表示します。\n\n"
            "```chatcore-artifact\n"
            f"{json.dumps(VALID_ARTIFACT, ensure_ascii=False)}\n"
        )

        normalized = normalize_response_with_artifacts(raw, recover_truncated=True)

        self.assertEqual(normalized.text, "表示します。")
        self.assertEqual(normalized.validation_errors, [])
        self.assertEqual(normalized.parts[1]["artifact"]["title"], "構成図")
        self.assertNotIn("chatcore-artifact", normalized.text)

    # 日本語: textから、unrepairabletruncationstripsbrokenblockことを検証します。
    # English: Verify that unrepairable truncation strips broken block from text.
    def test_unrepairable_truncation_strips_broken_block_from_text(self):
        raw = (
            "ツリーを表示します。\n\n"
            "```chatcore-artifact\n"
            '{"version":1,"title'
        )

        normalized = normalize_response_with_artifacts(raw, recover_truncated=True)

        # Falls back, but never dumps the broken JSON / fence into the UI text.
        self.assertNotIn("chatcore-artifact", normalized.text)
        self.assertNotIn('"version"', normalized.text)
        self.assertEqual(normalized.text, "ツリーを表示します。")

    # 日本語: streamingpassdoes〜しないsynthesizefallbackことを検証します。
    # English: Verify that streaming pass does not synthesize fallback.
    def test_streaming_pass_does_not_synthesize_fallback(self):
        raw = (
            "ツリーを表示します。\n\n"
            "```chatcore-artifact\n"
            '{"version":1,"title":"中央省庁ツリー","html":"<div id=\'app\'>'
        )

        normalized = normalize_response_with_artifacts(raw, allow_fallback=False)

        self.assertIsNone(normalized.parts)

    # 日本語: longprosementioningchartkeywordstaysplaintextことを検証します。
    # English: Verify that long prose mentioning chart keyword stays plain text.
    def test_long_prose_mentioning_chart_keyword_stays_plain_text(self):
        raw = (
            "藤沢市の天気の概要です。" + "詳細な気温や降水確率を説明します。" * 12 +
            "具体的な数値は、サイト上の表やグラフで確認してください。"
        )

        normalized = normalize_response_with_artifacts(raw)

        self.assertEqual(normalized.text, raw)
        self.assertIsNone(normalized.parts)

    # 日本語: Web検索traceblockが〜しないdumpedintofallbackことを検証します。
    # English: Verify that web search trace block is not dumped into fallback.
    def test_web_search_trace_block_is_not_dumped_into_fallback(self):
        trace_block = (
            '<details class="web-search-sources web-search-sources--trace">'
            '<summary class="web-search-sources__summary">'
            '<span class="web-search-sources__label">回答までのステップ</span>'
            '<span class="web-search-sources__count">4ステップ / 1件</span>'
            "</summary>"
            '<div class="web-search-sources__list">'
            '<ol class="web-search-sources__steps">'
            '<li class="web-search-sources__step">検索結果</li>'
            "</ol></div></details>"
        )
        raw = f"{trace_block}\n\n表示します。"

        normalized = normalize_response_with_artifacts(raw)

        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[1]["type"], "sandbox_artifact")
        artifact = normalized.parts[1]["artifact"]
        self.assertIn("fallback-ui", artifact["html"])
        self.assertNotIn("web-search-sources", artifact["html"])
        self.assertNotIn("回答までのステップ", artifact["html"])
        # トレースブロックは可視テキストには残り、フロントで参照リンクとして描画される。
        self.assertTrue(normalized.text.startswith(trace_block))

    # 日本語: decodemessagepartsdrops無効なartifactsことを検証します。
    # English: Verify that decode message parts drops invalid artifacts.
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
