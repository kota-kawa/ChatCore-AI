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

# 有効なアーティファクトの定義
# Definition of a valid artifact
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
    """
    Generative UI の機能や安全検証の仕様を検証するテストケースクラス
    Test case class to verify the functionality and safety validation specifications of Generative UI.
    """

    def test_normalize_response_extracts_valid_artifact_block(self):
        """
        正常なアーティファクトブロックを含むレスポンスから、アーティファクトが正しく抽出されることを検証します。
        Verify that a valid artifact block is correctly extracted from the response.
        """
        # 有効なアーティファクトブロックを含む生テキストを作成
        # Create raw text containing a valid artifact block
        raw = (
            "以下の図で整理しました。\n\n"
            "```chatcore-artifact\n"
            f"{json.dumps(VALID_ARTIFACT, ensure_ascii=False)}\n"
            "```"
        )

        # レスポンスの正規化処理を実行
        # Run the normalization process on the response
        normalized = normalize_response_with_artifacts(raw)

        # 抽出結果の検証：テキスト部分が正しく分離され、エラーがないこと
        # Assert the extraction results: text is split correctly and there are no validation errors
        self.assertEqual(normalized.text, "以下の図で整理しました。")
        self.assertEqual(normalized.validation_errors, [])
        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[0], {"type": "text", "text": "以下の図で整理しました。"})
        self.assertEqual(normalized.parts[1]["type"], "sandbox_artifact")
        self.assertEqual(normalized.parts[1]["artifact"]["title"], "構成図")

    def test_normalize_response_keeps_plain_text_unchanged(self):
        """
        アーティファクトを含まないプレーンテキストが、そのまま変更されずに保持されることを検証します。
        Verify that plain text containing no artifacts remains unchanged.
        """
        # プレーンテキストで正規化を実行
        # Run normalization with plain text
        normalized = normalize_response_with_artifacts("通常の回答です。")

        # 結果の検証：テキストが不変であり、partsが生成されないこと
        # Assert the results: text is unchanged and no parts are generated
        self.assertEqual(normalized.text, "通常の回答です。")
        self.assertIsNone(normalized.parts)

    def test_normalize_response_extracts_bare_json_artifact(self):
        """
        マークダウンフェンスで囲まれていない、生JSONのアーティファクトが正しく抽出されることを検証します。
        Verify that a bare JSON artifact (not enclosed in markdown fences) is correctly extracted.
        """
        # 生のJSONを含むテキストを作成
        # Create text containing a bare JSON string
        raw = (
            "表示します。\n\n"
            f"{json.dumps(VALID_ARTIFACT, ensure_ascii=False)}"
        )

        # 正規化を実行
        # Run normalization
        normalized = normalize_response_with_artifacts(raw)

        # 結果の検証：正しくパーツとして抽出されていること
        # Assert the results: correctly extracted as a sandbox_artifact part
        self.assertEqual(normalized.text, "表示します。")
        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[1]["type"], "sandbox_artifact")

    def test_normalize_response_extracts_generic_json_fence_artifact(self):
        """
        ```json フェンスで囲まれたアーティファクトが正しく抽出されることを検証します。
        Verify that an artifact enclosed in ```json fences is correctly extracted.
        """
        # jsonフェンスで囲まれたテキストを作成
        # Create text enclosed in a generic json markdown fence
        raw = (
            "表示します。\n\n"
            "```json\n"
            f"{json.dumps(VALID_ARTIFACT, ensure_ascii=False)}\n"
            "```"
        )

        # 正規化を実行
        # Run normalization
        normalized = normalize_response_with_artifacts(raw)

        # 結果の検証：正しくアーティファクトとして抽出されていること
        # Assert the results: correctly extracted as an artifact
        self.assertEqual(normalized.text, "表示します。")
        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[1]["artifact"]["title"], "構成図")

    def test_normalize_response_extracts_split_source_code_blocks(self):
        """
        html, css, js それぞれの独立したコードブロックからアーティファクトが再構成されることを検証します。
        Verify that an artifact is reconstructed from split code blocks of html, css, and js.
        """
        # html, css, js 各ブロックに分かれたマークダウンテキスト
        # Markdown text split into html, css, and js blocks
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

        # 正規化を実行
        # Run normalization
        normalized = normalize_response_with_artifacts(raw)

        # 結果の検証：個別のブロックが1つのアーティファクトに統合されていること
        # Assert the results: individual blocks are combined into one artifact
        self.assertEqual(normalized.text, "表示します。")
        self.assertEqual(normalized.validation_errors, [])
        self.assertIsNotNone(normalized.parts)
        artifact = normalized.parts[1]["artifact"]
        self.assertIn('<div id="app"></div>', artifact["html"])
        self.assertIn("#app{padding", artifact["css"])
        self.assertIn("textContent", artifact["js"])

    def test_base_prompt_few_shot_artifacts_are_valid_and_compact(self):
        """
        ベースとなるシステムプロンプトに含まれる Few-shot アーティファクト定義が有効であり、サイズ制限を満たしていることを検証します。
        Verify that few-shot artifacts defined in the base system prompt are valid and within size limits.
        """
        # システムプロンプトからアーティファクトブロックをすべて抽出
        # Extract all artifact blocks from the system prompt
        artifact_blocks = re.findall(
            r"```chatcore-artifact\s*(\{[\s\S]*?\})\s*```",
            BASE_SYSTEM_PROMPT,
        )

        # 少なくとも3つ以上のFew-shot例が存在することを検証
        # Verify that there are at least 3 few-shot examples
        self.assertGreaterEqual(len(artifact_blocks), 3)
        
        # 各アーティファクトブロックのパースと安全性の確認
        # Parse and validate safety for each artifact block
        for raw_payload in artifact_blocks:
            payload = json.loads(raw_payload)
            artifact = validate_artifact_payload(payload)

            # HTML内にapp IDが存在し、コード合計文字数が8000以下、高さが720以下であることを検証
            # Assert that app ID exists in HTML, total code length <= 8000, and height <= 720
            self.assertRegex(artifact["html"], r"id=[\"']app[\"']")
            self.assertLessEqual(
                len(artifact["html"]) + len(artifact["css"]) + len(artifact["js"]),
                8000,
            )
            self.assertLessEqual(artifact.get("height", 0), 720)

    def test_normalize_response_creates_fallback_for_short_display_intent(self):
        """
        JSONを含まない短い表示意図のテキストに対し、フォールバックUIが自動生成されることを検証します。
        Verify that a fallback UI is created for a short text expressing display intent without JSON.
        """
        # 表示意図のみの短いテキストで正規化を実行
        # Run normalization with a short text expressing intent to display
        normalized = normalize_response_with_artifacts("表示します。")

        # 結果の検証：フォールバックUIが生成され、タイトルに元のテキストが含まれること
        # Assert the results: a fallback UI is generated, using the original text as the title
        self.assertEqual(normalized.text, "表示します。")
        self.assertIsNotNone(normalized.parts)
        artifact = normalized.parts[1]["artifact"]
        self.assertEqual(artifact["title"], "表示します。")
        self.assertIn("fallback-ui", artifact["html"])

    def test_normalize_response_accepts_line_continuation_jsonish_artifact(self):
        """
        JSON内にバックスラッシュによる行継続(line continuation)が含まれていても、正しくデコードして抽出できることを検証します。
        Verify that a JSON-like payload with line continuation backslashes is accepted and normalized.
        """
        # 行継続のバックスラッシュを含むJSON風テキスト
        # JSON-like text containing line continuation backslashes
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

        # 正規化を実行
        # Run normalization
        normalized = normalize_response_with_artifacts(raw)

        # 各要素が正しくデコード・格納されていることを検証
        # Verify that all elements are correctly decoded and populated
        self.assertEqual(normalized.text, "表示します。")
        self.assertEqual(normalized.validation_errors, [])
        self.assertIsNotNone(normalized.parts)
        artifact = normalized.parts[1]["artifact"]
        self.assertEqual(artifact["title"], "Queue と Worker の流れ")
        self.assertIn(".box", artifact["css"])
        self.assertIn("const steps", artifact["js"])
        self.assertIn("style='font-family:sans-serif;padding:10px;'", artifact["html"])

    def test_validate_artifact_rejects_network_javascript(self):
        """
        JavaScriptコード内にネットワークリクエスト(fetchなど)が含まれている場合、検証エラーとして拒否されることを検証します。
        Verify that network request JavaScript (such as fetch) is rejected with a validation error.
        """
        # JSにfetchを含むアーティファクトを作成
        # Create an artifact with JavaScript including 'fetch'
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = "fetch('https://example.com')"

        # 検証エラーが送出されることを検証
        # Verify that a GenerativeUiValidationError is raised
        with self.assertRaises(GenerativeUiValidationError):
            validate_artifact_payload(artifact)

    def test_validate_artifact_rejects_worker_constructor(self):
        """
        JavaScriptコード内で Worker オブジェクトが生成されている場合、検証エラーとして拒否されることを検証します。
        Verify that the instantiation of a Worker in JavaScript is rejected with a validation error.
        """
        # JSにnew Workerを含むアーティファクトを作成
        # Create an artifact with JavaScript containing 'new Worker'
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = "new Worker('data:,')"

        # 検証エラーが送出されることを検証
        # Verify that a GenerativeUiValidationError is raised
        with self.assertRaises(GenerativeUiValidationError):
            validate_artifact_payload(artifact)

    def test_validate_artifact_allows_safe_html_event_handlers(self):
        """
        HTML内の安全なイベントハンドラ属性(onclickなど)が許容されることを検証します。
        Verify that safe HTML event handler attributes (such as onclick) are allowed.
        """
        # 安全なonclickハンドラを含むHTMLを設定
        # Set HTML containing a safe onclick handler
        artifact = dict(VALID_ARTIFACT)
        artifact["html"] = '<button id="b" onclick="this.textContent = \'Done\'">Click</button>'

        # ペイロード検証を実行
        # Execute payload validation
        normalized = validate_artifact_payload(artifact)

        # onclickがそのまま保持されていることを検証
        # Assert that 'onclick' is preserved
        self.assertIn("onclick", normalized["html"])

    def test_validate_artifact_removes_unsafe_html_event_handlers(self):
        """
        HTML内の危険なイベントハンドラ(親ウィンドウのpostMessage呼び出しなど)が自動的に除去されることを検証します。
        Verify that unsafe HTML event handlers (e.g., parent.postMessage) are stripped out.
        """
        # 危険なイベントハンドラを含むHTMLを設定
        # Set HTML containing an unsafe event handler
        artifact = dict(VALID_ARTIFACT)
        artifact["html"] = '<button onclick="parent.postMessage({type: \'x\'}, \'*\')">Click</button>'

        # ペイロード検証を実行
        # Execute payload validation
        normalized = validate_artifact_payload(artifact)

        # onclickが除去され、ボタンテキストは残ることを検証
        # Assert that 'onclick' is removed, but the button content remains
        self.assertNotIn("onclick", normalized["html"].lower())
        self.assertIn("Click", normalized["html"])

    def test_validate_artifact_allows_style_top_assignment(self):
        """
        JavaScriptコード内でのスタイル変更操作(style.topへの代入など)が許容されることを検証します。
        Verify that setting style properties (such as style.top) in JavaScript is allowed.
        """
        # JSにstyle.topの操作を含むアーティファクトを設定
        # Set an artifact with JavaScript operating on style.top
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = "document.getElementById('app').style.top = '8px';"

        # ペイロード検証を実行
        # Execute payload validation
        normalized = validate_artifact_payload(artifact)

        # 操作コードがそのまま保持されていることを検証
        # Assert that 'style.top' is preserved
        self.assertIn("style.top", normalized["js"])

    def test_validate_artifact_allows_property_access_named_top_and_parent(self):
        """
        他オブジェクトのプロパティ参照(rect.top、node.parentなど)が誤って拒否されないことを検証します。
        Verify that property access on non-window objects (rect.top, node.parent, etc.) is not rejected.
        """
        # レイアウト計算やツリー走査でよく使われるコードを含むアーティファクトを設定
        # Set an artifact with JavaScript commonly used for layout math and tree traversal
        artifact = dict(VALID_ARTIFACT)
        artifact["js"] = (
            "const rect = document.getElementById('app').getBoundingClientRect();"
            "const label = rect.top.toFixed(1);"
            "const node = {parent: {name: 'root'}};"
            "console.log(label, node.parent.name, node?.parent.name);"
        )

        # ペイロード検証を実行
        # Execute payload validation
        normalized = validate_artifact_payload(artifact)

        # コードがそのまま保持されていることを検証
        # Assert that the code is preserved
        self.assertIn("rect.top.toFixed", normalized["js"])
        self.assertIn("node.parent.name", normalized["js"])

    def test_validate_artifact_still_rejects_window_parent_access(self):
        """
        window.parent や裸の parent./top. などの親フレームアクセスは引き続き拒否されることを検証します。
        Verify that parent-frame access (window.parent, bare parent./top.) is still rejected.
        """
        for js in (
            "window.parent.location = 'https://example.com';",
            "parent.location = 'https://example.com';",
            "top.location.href = 'https://example.com';",
            "globalThis.top.x = 1;",
        ):
            artifact = dict(VALID_ARTIFACT)
            artifact["js"] = js

            # 検証エラーが送出されることを検証
            # Verify that a GenerativeUiValidationError is raised
            with self.assertRaises(GenerativeUiValidationError, msg=js):
                validate_artifact_payload(artifact)

    def test_validate_artifact_accepts_raw_control_characters_in_json_strings(self):
        """
        JSON文字列内に生のタブなどの制御文字が混ざっていてもアーティファクトとして抽出できることを検証します。
        Verify that raw control characters (e.g., tabs) inside JSON strings do not break extraction.
        """
        # HTML文字列に生のタブ文字を含むアーティファクトブロックを作成
        # Create an artifact block whose HTML string contains a raw tab character
        raw = (
            "整理しました。\n\n"
            "```chatcore-artifact\n"
            '{"version":1,"title":"タブ混入","html":"<div id=\'app\'>\ta\tb</div>"}\n'
            "```"
        )

        # レスポンスの正規化処理を実行
        # Run the normalization process on the response
        normalized = normalize_response_with_artifacts(raw)

        # アーティファクトが抽出され、エラーが無いことを検証
        # Assert the artifact is extracted without validation errors
        self.assertEqual(normalized.validation_errors, [])
        self.assertEqual(normalized.parts[1]["type"], "sandbox_artifact")
        self.assertIn("a\tb", normalized.parts[1]["artifact"]["html"])

    def test_validate_artifact_strips_truncated_banned_tag_fragment(self):
        """
        出力打ち切りで閉じられなかった禁止タグの断片が除去され、アーティファクト全体は拒否されないことを検証します。
        Verify that a banned-tag fragment cut off by truncation is stripped instead of rejecting the artifact.
        """
        # 末尾が `<script ...` のまま途切れたHTMLを設定
        # Set HTML that ends mid-way through an unclosed `<script ...` tag
        artifact = dict(VALID_ARTIFACT)
        artifact["html"] = '<div id="app">グラフ</div><script type="mod'

        # ペイロード検証を実行
        # Execute payload validation
        normalized = validate_artifact_payload(artifact)

        # 断片が除去され、本文は保持されることを検証
        # Assert the fragment is removed while the body is preserved
        self.assertNotIn("<script", normalized["html"].lower())
        self.assertIn("グラフ", normalized["html"])

    def test_validate_artifact_accepts_common_aliases_and_embedded_code(self):
        """
        アーティファクトキーのエイリアス(titleの代わりにname、js/cssがhtmlに埋め込まれているケースなど)が正しく正規化されることを検証します。
        Verify that alternative payload formats and aliases are successfully normalized.
        """
        # エイリアスや埋め込みタグを含むアーティファクト定義
        # Artifact with alternative keys and embedded style/script tags
        artifact = {
            "name": "Alias UI",
            "body": "<style>#app{color:red;}</style><div id=\"app\"></div><script>document.getElementById('app').textContent='ok';</script>",
            "height": "1200px",
        }

        # ペイロード検証を実行
        # Execute payload validation
        normalized = validate_artifact_payload(artifact)

        # 各項目が標準のキーにマッピングされ、タグが分離されていることを検証
        # Assert that keys are mapped and tags are split into separate attributes
        self.assertEqual(normalized["title"], "Alias UI")
        self.assertEqual(normalized["height"], 900)
        self.assertNotIn("<script", normalized["html"].lower())
        self.assertIn("#app{color:red;}", normalized["css"])
        self.assertIn("textContent='ok'", normalized["js"])

    def test_normalize_response_uses_fallback_when_artifact_validation_fails(self):
        """
        アーティファクトのバリデーションに失敗した場合に、自動的にフォールバックUIが適用されることを検証します。
        Verify that the normalizer uses a fallback UI when artifact validation fails.
        """
        # JSにfetchを含む不正なアーティファクトブロックを設定
        # Set raw text containing an invalid artifact block with 'fetch'
        raw = (
            "短い説明です。\n\n"
            "```chatcore-artifact\n"
            '{"version":1,"title":"Bad","html":"<div></div>","css":"","js":"fetch(\'https://example.com\')"}\n'
            "```"
        )

        # 正規化を実行
        # Run normalization
        normalized = normalize_response_with_artifacts(raw)

        # 結果の検証：フォールバックUIが適用され、バリデーションエラーが記録されること
        # Assert the results: fallback UI is applied and validation errors are recorded
        self.assertEqual(normalized.text, "短い説明です。")
        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[1]["type"], "sandbox_artifact")
        self.assertIn("fallback-ui", normalized.parts[1]["artifact"]["html"])
        self.assertNotIn("安全検証", normalized.text)
        self.assertTrue(normalized.validation_errors)

    def test_validate_artifact_adds_default_app_root_for_empty_html(self):
        """
        HTMLが空である場合、デフォルトのアプリルート要素(<div id="app">)が自動で追加されることを検証します。
        Verify that a default app root div is added to the HTML if it is empty.
        """
        # htmlキーが空のアーティファクト
        # Artifact with empty HTML string
        artifact = dict(VALID_ARTIFACT)
        artifact["html"] = ""
        artifact["js"] = "document.getElementById('app').textContent = 'ready';"

        # ペイロード検証を実行
        # Execute payload validation
        normalized = validate_artifact_payload(artifact)

        # デフォルト要素が追加されていることを検証
        # Assert that the app root element is added
        self.assertIn('id="app"', normalized["html"])

    def test_recovers_truncated_artifact_cut_off_inside_string(self):
        """
        文字列の途中で途切れた不完全なアーティファクトブロックが、正しく修復・抽出されることを検証します。
        Verify that a truncated artifact cut off inside a JSON string is recovered.
        """
        # 途中で切れているアーティファクトブロック
        # Truncated artifact block cut off in the middle
        raw = (
            "ツリーを表示します。\n\n"
            "```chatcore-artifact\n"
            '{"version":1,"title":"中央省庁ツリー","description":"主要省庁","height":520,'
            "\"html\":\"<div id='app'><ul class='tree'><li>"
            "<button class='tog'>復興庁</button><ul class='sub'><li>"
        )

        # 修復を有効にして正規化を実行
        # Run normalization with recovery enabled
        normalized = normalize_response_with_artifacts(raw, recover_truncated=True)

        # 結果の検証：パースに成功し、元のテキストにJSONの残骸が露出していないこと
        # Assert the results: successfully parsed, and broken JSON text does not leak into output
        self.assertEqual(normalized.text, "ツリーを表示します。")
        self.assertEqual(normalized.validation_errors, [])
        self.assertIsNotNone(normalized.parts)
        artifact = normalized.parts[1]["artifact"]
        self.assertEqual(artifact["title"], "中央省庁ツリー")
        self.assertIn("復興庁", artifact["html"])
        self.assertNotIn("fallback-ui", artifact["html"])
        self.assertNotIn("chatcore-artifact", normalized.text)
        self.assertNotIn('"version"', normalized.text)

    def test_recovers_complete_artifact_missing_closing_fence(self):
        """
        JSONとしては完成しているが、末尾のマークダウンフェンス(```)が欠落しているアーティファクトブロックを修復できることを検証します。
        Verify that a complete artifact payload missing its closing markdown fence is recovered.
        """
        # フェンス閉じのないテキスト
        # Text without a closing markdown fence
        raw = (
            "表示します。\n\n"
            "```chatcore-artifact\n"
            f"{json.dumps(VALID_ARTIFACT, ensure_ascii=False)}\n"
        )

        # 修復を有効にして正規化を実行
        # Run normalization with recovery enabled
        normalized = normalize_response_with_artifacts(raw, recover_truncated=True)

        # 結果の検証：正しく抽出でき、フェンス等がテキストに残らないこと
        # Assert the results: correctly extracted and no fences are left in the text
        self.assertEqual(normalized.text, "表示します。")
        self.assertEqual(normalized.validation_errors, [])
        self.assertEqual(normalized.parts[1]["artifact"]["title"], "構成図")
        self.assertNotIn("chatcore-artifact", normalized.text)

    def test_unrepairable_truncation_strips_broken_block_from_text(self):
        """
        修復不可能なレベルで破損したアーティファクトブロックが、画面上にゴミとして露出しないよう適切に除去されることを検証します。
        Verify that a completely unrepairable broken artifact block is stripped from the display text.
        """
        # 修復不能なほど短い途切れデータ
        # Truncated string too short to repair
        raw = (
            "ツリーを表示します。\n\n"
            "```chatcore-artifact\n"
            '{"version":1,"title'
        )

        # 修復を有効にして正規化を実行
        # Run normalization with recovery enabled
        normalized = normalize_response_with_artifacts(raw, recover_truncated=True)

        # 結果の検証：JSONがテキストに露出せず、元の説明文のみが表示されること
        # Assert the results: JSON text does not leak, and only the description remains
        self.assertNotIn("chatcore-artifact", normalized.text)
        self.assertNotIn('"version"', normalized.text)
        self.assertEqual(normalized.text, "ツリーを表示します。")

    def test_streaming_pass_does_not_synthesize_fallback(self):
        """
        ストリーミング中(allow_fallback=False)は、不完全なアーティファクトであってもフォールバックUIの生成を行わないことを検証します。
        Verify that streaming pass (with allow_fallback=False) does not generate a fallback UI.
        """
        # 途中で切れているアーティファクトブロック
        # Truncated artifact block
        raw = (
            "ツリーを表示します。\n\n"
            "```chatcore-artifact\n"
            '{"version":1,"title":"中央省庁ツリー","html":"<div id=\'app\'>'
        )

        # フォールバック無効で正規化を実行
        # Run normalization without fallback
        normalized = normalize_response_with_artifacts(raw, allow_fallback=False)

        # 結果の検証：パーツが生成されないこと
        # Assert that no parts are synthesized
        self.assertIsNone(normalized.parts)

    def test_long_prose_mentioning_chart_keyword_stays_plain_text(self):
        """
        「グラフ」などのキーワードを含みつつも、単に長い散文であるテキストが、誤ってアーティファクトと誤認されないことを検証します。
        Verify that a long text mentioning a keyword like 'chart' is not incorrectly treated as an artifact.
        """
        # キーワードを含み、長い文章を作成
        # Create a long text containing keywords
        raw = (
            "藤沢市の天気の概要です。" + "詳細な気温や降水確率を説明します。" * 12 +
            "具体的な数値は、サイト上の表やグラフで確認してください。"
        )

        # 正規化を実行
        # Run normalization
        normalized = normalize_response_with_artifacts(raw)

        # 結果の検証：そのままテキストとして保持されること
        # Assert the results: text is kept unchanged
        self.assertEqual(normalized.text, raw)
        self.assertIsNone(normalized.parts)

    def test_web_search_trace_block_is_not_dumped_into_fallback(self):
        """
        Web検索時の進捗/トレース表示ブロックが、フォールバックUIの生成ロジックに巻き込まれて除去されないことを検証します。
        Verify that web search progress/trace block is preserved and not swallowed by fallback UI logic.
        """
        # Web検索時のトレースブロックを含むテキストを作成
        # Create text containing a web search trace block
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

        # 正規化を実行
        # Run normalization
        normalized = normalize_response_with_artifacts(raw)

        # 結果の検証：フォールバックUIは生成されつつ、トレース部分はテキストに保持されていること
        # Assert the results: fallback UI is created, and the trace block remains in the text
        self.assertIsNotNone(normalized.parts)
        self.assertEqual(normalized.parts[1]["type"], "sandbox_artifact")
        artifact = normalized.parts[1]["artifact"]
        self.assertIn("fallback-ui", artifact["html"])
        self.assertNotIn("web-search-sources", artifact["html"])
        self.assertNotIn("回答までのステップ", artifact["html"])
        self.assertTrue(normalized.text.startswith(trace_block))

    def test_decode_message_parts_drops_invalid_artifacts(self):
        """
        メッセージパーツをデコードする際、安全検証に引っかかる不正なアーティファクトが自動的にドロップされることを検証します。
        Verify that decoding message parts filters out and drops invalid artifacts.
        """
        # 安全でないJS(window.topへのアクセスなど)を含むパーツの定義
        # Define parts containing unsafe JavaScript (e.g., accessing window.top)
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

        # デコード処理結果の検証：不正なアーティファクトのみが除去されること
        # Assert the results: only the invalid artifact is dropped
        self.assertEqual(decode_message_parts(parts), [{"type": "text", "text": "hello"}])


if __name__ == "__main__":
    # テストを実行します
    # Execute the tests
    unittest.main()
