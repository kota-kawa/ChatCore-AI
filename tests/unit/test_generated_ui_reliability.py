from __future__ import annotations

import json
import unittest
from typing import Any
from unittest import mock

from services.chat_generation import ChatGenerationJob
from services.chat_generation_telemetry import ChatGenerationTelemetry
from services.generative_ui import (
    GenerativeUiValidationError,
    artifact_status_part,
    decode_message_parts,
    encode_message_parts,
    inject_generative_ui_mode_instruction,
    is_explicit_generative_ui_opt_out,
    normalize_response_with_artifact_retry,
    normalize_response_with_artifacts,
    requested_artifact_quality_issues,
    validate_artifact_payload,
)
from services.generative_ui_javascript import javascript_structure_error
from services.llm import LlmOutputLimitError
from services.user_skills import GENERATIVE_UI_EXECUTION_CONTRACT

VALID_ARTIFACT: dict[str, Any] = {
    "version": 1,
    "title": "比較マップ",
    "description": "2案の違いを視覚的に比較します",
    "height": 420,
    "html": (
        '<div id="app"><header><span>Comparison</span><h2>2案の特徴</h2></header>'
        '<main><article><strong>A案</strong><p>速度を優先する構成です。</p></article>'
        '<article><strong>B案</strong><p>品質を優先する構成です。</p></article></main></div>'
    ),
    "css": (
        "#app{padding:24px;border-radius:18px;background:linear-gradient(135deg,#f8fafc,#eef2ff);"
        "color:#172033;font:14px/1.6 system-ui,sans-serif}header{margin-bottom:18px}header span{"
        "color:#4f46e5;font-weight:700}h2{margin:4px 0;font-size:22px}main{display:grid;"
        "grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}article{padding:18px;border:1px solid #cbd5e1;"
        "border-radius:14px;background:#fff;box-shadow:0 12px 28px #1e3a8a14}article p{color:#475569}"
    ),
    "js": (
        "const app=document.getElementById('app');"
        "app.querySelectorAll('article').forEach((card)=>card.addEventListener('click',()=>{"
        "app.querySelectorAll('article').forEach((item)=>item.classList.remove('active'));"
        "card.classList.add('active');}));"
    ),
}


# 品質ゲートを通る完成度の生成UI。修復が成功した場合の入力として使う。
# A generated UI complete enough to pass the quality gate, used as a successful repair result.
POLISHED_ARTIFACT = {
    "version": 1,
    "title": "優先度マップ",
    "description": "項目を選択して詳細を確認できます",
    "height": 420,
    "html": (
        '<div id="app"><header><span>Priority map</span><h2>今週の重点項目</h2></header>'
        '<main><button class="item active">品質改善</button><button class="item">速度改善</button>'
        '<section><strong>品質改善</strong><p>失敗率を下げて初回表示を安定させます。</p></section></main></div>'
    ),
    "css": (
        "#app{padding:24px;border-radius:18px;background:linear-gradient(135deg,#f8fafc,#eef2ff);"
        "color:#172033;font:14px/1.6 system-ui,sans-serif;box-shadow:0 16px 36px #1e3a8a1a}"
        "header{margin-bottom:18px}header span{color:#4f46e5;font-weight:700}h2{margin:4px 0;font-size:22px}"
        "main{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.item,section{padding:14px;"
        "border:1px solid #cbd5e1;border-radius:12px;background:#fff}.active{color:#fff;background:#4f46e5}"
        "section{grid-column:1/-1}section p{margin:6px 0 0;color:#475569}"
    ),
    "js": (
        "const app=document.getElementById('app');app.querySelectorAll('.item').forEach((button)=>"
        "button.addEventListener('click',()=>{app.querySelectorAll('.item').forEach((item)=>"
        "item.classList.remove('active'));button.classList.add('active');}));"
    ),
}


def _artifact_block(payload: dict[str, Any] | None = None, *, introduction: str = "生成しました。") -> str:
    artifact = payload or VALID_ARTIFACT
    return (
        f"{introduction}\n\n```chatcore-artifact\n"
        f"{json.dumps(artifact, ensure_ascii=False)}\n"
        "```"
    )


def _artifact_parts(result: Any) -> list[dict[str, Any]]:
    return [
        part
        for part in (result.parts or [])
        if isinstance(part, dict) and part.get("type") == "sandbox_artifact"
    ]


class GeneratedUiIntentReliabilityTests(unittest.TestCase):
    def test_classifier_none_or_unknown_does_not_discard_a_safe_canonical_artifact(self):
        raw = _artifact_block()

        for mode in ("NONE", None):
            with self.subTest(mode=mode):
                normalized = normalize_response_with_artifacts(
                    raw,
                    recover_truncated=True,
                    ui_mode=mode,
                )

                self.assertEqual(normalized.validation_errors, [])
                self.assertEqual(normalized.artifact_status, "valid")
                self.assertEqual(len(_artifact_parts(normalized)), 1)

    def test_only_an_explicit_ui_opt_out_suppresses_a_canonical_artifact(self):
        normalized = normalize_response_with_artifacts(
            _artifact_block(),
            recover_truncated=True,
            ui_mode="NONE",
            explicit_ui_opt_out=True,
        )

        self.assertEqual(normalized.text, "生成しました。")
        self.assertIsNone(normalized.parts)
        self.assertEqual(normalized.artifact_status, "suppressed")
        self.assertIn("explicit_ui_opt_out", normalized.artifact_reason_codes)

    def test_explicit_opt_out_detection_requires_an_actual_negation(self):
        positive_requests = (
            "比較を生成UIで見せて",
            "図はどのように作るのか説明して",
            "Create an interactive timeline.",
        )
        negative_requests = (
            "文章だけで説明して。図はいりません。",
            "生成UIは使わず、テキストのみで回答して",
            "No UI or diagram; answer in prose only.",
        )

        for request in positive_requests:
            with self.subTest(request=request):
                self.assertFalse(is_explicit_generative_ui_opt_out(request))
        for request in negative_requests:
            with self.subTest(request=request):
                self.assertTrue(is_explicit_generative_ui_opt_out(request))

    def test_selected_mode_is_injected_as_a_required_generation_instruction(self):
        original = [{"role": "user", "content": "比較を生成UIで見せて"}]

        injected = inject_generative_ui_mode_instruction(original, "2D")

        self.assertEqual(original, [{"role": "user", "content": "比較を生成UIで見せて"}])
        mode_messages = [
            message
            for message in injected
            if message.get("role") in {"system", "developer"}
            and "2D" in str(message.get("content") or "")
        ]
        self.assertEqual(len(mode_messages), 1)
        self.assertIn("required", str(mode_messages[0]["content"]).lower())

    def test_required_mode_without_an_artifact_has_a_machine_readable_failure_reason(self):
        normalized = normalize_response_with_artifacts(
            "比較結果はA案が優位です。",
            ui_mode="2D",
        )

        self.assertIsNone(normalized.parts)
        self.assertEqual(normalized.artifact_status, "missing")
        self.assertIn("required_artifact_missing", normalized.artifact_reason_codes)


class GeneratedUiRepairReliabilityTests(unittest.TestCase):
    def test_malformed_json_uses_the_artifact_repair_prompt(self):
        malformed = (
            "生成しました。\n\n```chatcore-artifact\n"
            "{'version':1,'title':'比較','html':'<div id=\"app\"></div>',"
            "'css':'#app{padding:20px}','js':''}\n```"
        )
        captured_messages: list[list[dict[str, Any]]] = []

        def generate_response(messages: list[dict[str, Any]], _model: str) -> str:
            captured_messages.append(messages)
            return _artifact_block(introduction="")

        normalized = normalize_response_with_artifact_retry(
            malformed,
            conversation_messages=[{"role": "user", "content": "比較を生成UIで見せて"}],
            model="test-model",
            generate_response=generate_response,
            user_request="比較を生成UIで見せて",
            ui_mode="2D",
        )

        self.assertEqual(len(captured_messages), 1)
        repair_prompt = "\n".join(
            str(message.get("content") or "")
            for message in captured_messages[0]
            if message.get("role") in {"system", "developer"}
        )
        self.assertIn("artifact_malformed", repair_prompt)
        self.assertIn("valid JSON", repair_prompt)
        self.assertTrue(normalized.repair_attempted)
        self.assertEqual(normalized.artifact_status, "valid")
        self.assertEqual(len(_artifact_parts(normalized)), 1)

    def test_malformed_fence_is_identified_before_repair(self):
        malformed_fence = (
            "生成しました。\n\n```generative-ui\n"
            f"{json.dumps(VALID_ARTIFACT, ensure_ascii=False)}\n```"
        )
        captured_messages: list[list[dict[str, Any]]] = []

        normalized = normalize_response_with_artifact_retry(
            malformed_fence,
            conversation_messages=[{"role": "user", "content": "比較を生成UIで見せて"}],
            model="test-model",
            generate_response=lambda messages, _model: captured_messages.append(messages)
            or _artifact_block(introduction=""),
            user_request="比較を生成UIで見せて",
            ui_mode="2D",
        )

        repair_prompt = "\n".join(str(message.get("content") or "") for message in captured_messages[0])
        self.assertIn("artifact_malformed", repair_prompt)
        self.assertTrue(normalized.repair_attempted)
        self.assertEqual(normalized.artifact_status, "valid")

    def test_repair_prompt_does_not_inherit_competing_turn_protocols(self):
        conversation = [
            {"role": "system", "content": "Always emit <turn_state_update> JSON before answering."},
            {"role": "user", "content": "比較を生成UIで見せて"},
            {"role": "assistant", "content": "<turn_state_update>{}</turn_state_update>"},
        ]
        captured_messages: list[list[dict[str, Any]]] = []

        normalize_response_with_artifact_retry(
            "比較結果を文章で説明します。",
            conversation_messages=conversation,
            model="test-model",
            generate_response=lambda messages, _model: captured_messages.append(messages)
            or _artifact_block(introduction=""),
            user_request="比較を生成UIで見せて",
            ui_mode="2D",
        )

        repair_prompt = "\n".join(
            str(message.get("content") or "") for message in captured_messages[0]
        )
        self.assertNotIn("turn_state_update", repair_prompt)
        self.assertEqual(captured_messages[0][-1], {"role": "user", "content": "比較を生成UIで見せて"})

    def test_repair_output_limit_is_not_reported_as_a_success(self):
        def output_limited(_messages: list[dict[str, Any]], _model: str) -> str:
            raise LlmOutputLimitError("repair output reached its limit")

        normalized = normalize_response_with_artifact_retry(
            "比較結果を文章で説明します。",
            conversation_messages=[{"role": "user", "content": "比較を生成UIで見せて"}],
            model="test-model",
            generate_response=output_limited,
            user_request="比較を生成UIで見せて",
            ui_mode="2D",
        )

        self.assertTrue(normalized.repair_attempted)
        self.assertEqual(normalized.artifact_status, "repair_failed")
        self.assertIn("artifact_repair_output_limited", normalized.artifact_reason_codes)
        self.assertFalse(_artifact_parts(normalized))

    def test_incomplete_repair_is_not_reported_as_a_success(self):
        normalized = normalize_response_with_artifact_retry(
            "比較結果を文章で説明します。",
            conversation_messages=[{"role": "user", "content": "比較を生成UIで見せて"}],
            model="test-model",
            generate_response=lambda *_args: (
                "```chatcore-artifact\n"
                '{"version":1,"title":"比較","html":"<div id=\\"app\\">'
            ),
            user_request="比較を生成UIで見せて",
            ui_mode="2D",
        )

        self.assertTrue(normalized.repair_attempted)
        self.assertEqual(normalized.artifact_status, "repair_failed")
        self.assertIn("artifact_repair_invalid", normalized.artifact_reason_codes)
        self.assertFalse(_artifact_parts(normalized))


class GeneratedUiValidationReliabilityTests(unittest.TestCase):
    def test_javascript_syntax_errors_are_rejected_before_browser_execution(self):
        for javascript in ("const = ;", "function broken( {"):
            with self.subTest(javascript=javascript):
                with self.assertRaisesRegex(GenerativeUiValidationError, "syntax"):
                    validate_artifact_payload({**VALID_ARTIFACT, "js": javascript})

    def test_unknown_libraries_are_rejected_instead_of_silently_removed(self):
        with self.assertRaisesRegex(GenerativeUiValidationError, "Unsupported.*d3|unsupported.*d3"):
            validate_artifact_payload(
                {
                    **VALID_ARTIFACT,
                    "libraries": ["d3"],
                    "js": "d3.select('#app').append('div').text('ready');",
                }
            )

    def test_supported_javascript_and_three_library_remain_valid(self):
        two_dimensional = validate_artifact_payload(VALID_ARTIFACT)
        three_dimensional = validate_artifact_payload(
            {
                **VALID_ARTIFACT,
                "libraries": ["three"],
                "js": "const scene = new THREE.Scene(); const geometry = new THREE.BoxGeometry(1,1,1);",
            }
        )

        self.assertIn("addEventListener", two_dimensional["js"])
        self.assertEqual(three_dimensional["libraries"], ["three"])


# gpt-oss-120b で実際に観測した失敗形。モデルは JSON 文字列の中で改行と引用符を
# 二重にエスケープし、`\n` や `\"` をそのままブラウザへ届けてしまう。
# The failure shape observed from gpt-oss-120b: the model escapes newlines and quotes twice
# inside the JSON strings, so a literal `\n` or `\"` reaches the browser.
GOOD_ARTIFACT_SOURCES: dict[str, str] = {
    "html": '<div id="app"></div>',
    "css": (
        "#app{padding:24px;max-width:420px;margin:0 auto;font-family:system-ui,sans-serif;"
        "color:#0f172a;background:#ffffff}\n"
        "h2{margin:0 0 16px;font-size:17px}\n"
        ".step{padding:12px 16px;border:1px solid #94a3b8;border-radius:10px;background:#f8fafc;"
        "text-align:center;font-weight:600}\n"
        ".arrow{color:#64748b;text-align:center;margin:8px 0;font-size:15px}"
    ),
    "js": (
        "const steps = ['申請', '上長承認', '経理確認', '支払'];\n"
        "const app = document.getElementById('app');\n"
        "app.innerHTML = '<h2>承認フロー</h2>' + steps\n"
        "  .map(function (step) { return '<div class=\"step\">' + step + '</div>'; })\n"
        "  .join('<div class=\"arrow\">to</div>');\n"
        "app.addEventListener('click', function (event) {\n"
        "  const step = event.target.closest('.step');\n"
        "  if (step) { step.classList.toggle('done'); }\n"
        "});"
    ),
}


def _artifact_response(**overrides: Any) -> str:
    """Render one artifact response exactly as a model would emit it."""
    payload = {
        "version": 1,
        "title": "承認フロー",
        "description": "申請から支払まで",
        "height": 360,
        **GOOD_ARTIFACT_SOURCES,
        **overrides,
    }
    return (
        "承認フローを可視化しました。\n\n```chatcore-artifact\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n```"
    )


def _double_escaped_artifact_response() -> str:
    """Emit the same artifact with every source escaped one level too many."""
    over_escaped = {
        key: value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
        for key, value in GOOD_ARTIFACT_SOURCES.items()
    }
    return _artifact_response(**over_escaped)


class GeneratedUiSourceRecoveryTests(unittest.TestCase):
    """二重エスケープ・DOM外殻・#app欠落を、モデルに投げ返さず決定的に直せているか。

    Whether double escaping, a document shell, and a missing #app are repaired
    deterministically instead of being bounced back to the model.
    """

    def test_a_double_escaped_payload_is_decoded_instead_of_rendering_blank(self):
        normalized = normalize_response_with_artifacts(
            _double_escaped_artifact_response(),
            recover_truncated=True,
            ui_mode="2D",
        )

        self.assertEqual(normalized.validation_errors, [])
        artifact = next(
            part["artifact"]
            for part in (normalized.parts or [])
            if part["type"] == "sandbox_artifact"
        )
        self.assertIn('id="app"', artifact["html"])
        self.assertNotIn("\\\"", artifact["html"])
        self.assertIn("\n", artifact["js"])
        self.assertNotIn("\\n", artifact["js"])
        self.assertEqual(requested_artifact_quality_issues(normalized, "2D"), [])

    def test_correctly_escaped_javascript_keeps_its_string_escapes(self):
        artifact = validate_artifact_payload(
            {
                **VALID_ARTIFACT,
                "js": "const lines = 'a\\nb'.split('\\n');\ndocument.getElementById('app').title = lines[0];",
            }
        )

        self.assertIn("'a\\nb'", artifact["js"])

    def test_an_app_root_is_added_when_the_javascript_looks_it_up(self):
        artifact = validate_artifact_payload(
            {
                **VALID_ARTIFACT,
                "html": "<section><h2>四半期売上</h2><p>Q1 から Q4 まで</p></section>",
                "js": "document.getElementById('app').dataset.ready = 'yes';",
            }
        )

        self.assertIn('id="app"', artifact["html"])
        self.assertIn("四半期売上", artifact["html"])

    def test_markup_without_an_app_lookup_is_left_alone(self):
        artifact = validate_artifact_payload(
            {
                **VALID_ARTIFACT,
                "html": "<section><h2>四半期売上</h2><p>Q1 から Q4 まで</p></section>",
                "js": "document.querySelector('h2').dataset.ready = 'yes';",
            }
        )

        self.assertEqual(
            artifact["html"], "<section><h2>四半期売上</h2><p>Q1 から Q4 まで</p></section>"
        )

    def test_a_full_document_shell_is_unwrapped_to_its_body(self):
        artifact = validate_artifact_payload(
            {
                **VALID_ARTIFACT,
                "html": (
                    "<!DOCTYPE html><html><head><title>Gantt</title></head>"
                    '<body><div id="app"></div></body></html>'
                ),
            }
        )

        self.assertEqual(artifact["html"].strip(), '<div id="app"></div>')


class GeneratedUiJavaScriptScanTests(unittest.TestCase):
    def test_an_ordinary_anonymous_function_is_not_treated_as_the_function_constructor(self):
        artifact = validate_artifact_payload(
            {
                **VALID_ARTIFACT,
                "js": (
                    "(function(){\n"
                    "  const app = document.getElementById('app');\n"
                    "  app.addEventListener('click', function(){ app.dataset.hit = '1'; });\n"
                    "})();"
                ),
            }
        )

        self.assertIn("(function(){", artifact["js"])

    def test_building_code_from_a_string_is_still_rejected(self):
        for javascript in (
            "const run = new Function('return 1'); run();",
            "const run = Function('return 1'); run();",
            "eval('1 + 1');",
        ):
            with self.subTest(javascript=javascript):
                with self.assertRaisesRegex(GenerativeUiValidationError, "not allowed"):
                    validate_artifact_payload({**VALID_ARTIFACT, "js": javascript})

    def test_a_broken_expression_inside_a_template_substitution_is_rejected(self):
        with self.assertRaisesRegex(GenerativeUiValidationError, "syntax"):
            validate_artifact_payload(
                {
                    **VALID_ARTIFACT,
                    "js": (
                        "const rows = ['a'];\n"
                        "const app = document.getElementById('app');\n"
                        "app.innerHTML = `<b>${rows.map((row) => row.toUpperCase()}</b>`;"
                    ),
                }
            )

    def test_a_valid_template_substitution_is_accepted(self):
        artifact = validate_artifact_payload(
            {
                **VALID_ARTIFACT,
                "js": (
                    "const rows = [{ name: 'A', done: true }];\n"
                    "const app = document.getElementById('app');\n"
                    "app.innerHTML = rows.map((row) => "
                    "`<div class=\"row${row.done ? ' done' : ''}\">${row.name}</div>`).join('');"
                ),
            }
        )

        self.assertIn("row.done", artifact["js"])

    def test_an_unterminated_string_literal_is_a_structural_error(self):
        self.assertIn(
            "unterminated",
            javascript_structure_error("const label = 'long text\nconst next = 1;") or "",
        )

    def test_trailing_output_after_the_closing_brace_does_not_lose_the_artifact(self):
        payload = json.dumps(
            {"version": 1, "title": "承認フロー", **GOOD_ARTIFACT_SOURCES}, ensure_ascii=False
        )
        for trailing in ("}", '"', "</div>"):
            with self.subTest(trailing=trailing):
                normalized = normalize_response_with_artifacts(
                    "承認フローです。\n\n```chatcore-artifact\n" + payload + trailing + "\n```",
                    recover_truncated=True,
                    ui_mode="2D",
                )

                self.assertEqual(normalized.validation_errors, [])
                self.assertTrue(normalized.has_artifact())
                self.assertEqual(normalized.text, "承認フローです。")

    def test_an_escape_that_is_invalid_in_json_is_read_as_a_literal_backslash(self):
        # JS のテンプレート内の `` \` `` を JSON へ入れるとき、モデルは `\\` を1つ落とす。
        # Putting `` \` `` from a JS template into JSON, models drop one `\\`.
        payload = (
            '{"version":1,"title":"t","html":"<div id=\\"app\\"></div>",'
            '"css":"#app{padding:20px}","js":"const app=document.getElementById(\'app\');'
            'app.textContent=`\\`ok\\``;"}'
        )
        normalized = normalize_response_with_artifacts(
            "できました。\n\n```chatcore-artifact\n" + payload + "\n```",
            recover_truncated=True,
            ui_mode="2D",
        )

        self.assertEqual(normalized.validation_errors, [])
        self.assertTrue(normalized.has_artifact())

    def test_lookalike_punctuation_in_code_is_repaired_without_touching_strings(self):
        artifact = validate_artifact_payload(
            {
                **VALID_ARTIFACT,
                "js": (
                    "const points = [[\u22121, 2], [3, \u22124]];\n"
                    "const label = '\u7bc4\u56f2\u306f \u22121 \u304b\u3089 1\uff08\u4e21\u7aef\uff09';\n"
                    "document.getElementById('app').dataset.count = points.length + label.length;"
                ),
            }
        )

        self.assertIn("[[-1, 2], [3, -4]]", artifact["js"])
        self.assertIn("\u22121 \u304b\u3089 1\uff08\u4e21\u7aef\uff09", artifact["js"])

    def test_a_stray_backslash_outside_a_string_is_a_structural_error(self):
        self.assertIn(
            "stray backslash",
            javascript_structure_error(r"const app = 1;\nif (app) { app += \1; }") or "",
        )

    def test_a_javascript_only_over_escape_is_recovered_rather_than_rejected(self):
        artifact = validate_artifact_payload(
            {**VALID_ARTIFACT, "js": r"const app = document.getElementById('app');\napp.hidden = false;"}
        )

        self.assertIn("\n", artifact["js"])
        self.assertNotIn("\\n", artifact["js"])


class GeneratedUiQualityGateTests(unittest.TestCase):
    def test_a_javascript_rendered_interface_is_not_called_sparse(self):
        normalized = normalize_response_with_artifacts(
            "売上を可視化しました。\n\n```chatcore-artifact\n"
            + json.dumps(
                {
                    **VALID_ARTIFACT,
                    "html": '<div id="app"></div>',
                    "css": (
                        "#app{padding:24px;font-family:system-ui,sans-serif;color:#0f172a}\n"
                        ".chart{display:flex;align-items:flex-end;gap:16px;height:240px}\n"
                        ".bar{flex:1;background:#4f46e5;border-radius:6px 6px 0 0}"
                    ),
                    "js": (
                        "const data = [120, 150, 90, 210];\n"
                        "const app = document.getElementById('app');\n"
                        "app.innerHTML = '<div class=\"chart\">' + data.map((value) => "
                        "'<div class=\"bar\" style=\"height:' + value + 'px\"></div>').join('') + '</div>';\n"
                        "app.addEventListener('click', (event) => {\n"
                        "  const bar = event.target.closest('.bar');\n"
                        "  if (bar) { bar.classList.toggle('selected'); }\n"
                        "});"
                    ),
                },
                ensure_ascii=False,
            )
            + "\n```",
            ui_mode="2D",
        )

        self.assertEqual(requested_artifact_quality_issues(normalized, "2D"), [])

    def test_markup_driven_content_still_has_to_carry_something(self):
        normalized = normalize_response_with_artifacts(
            "できました。\n\n```chatcore-artifact\n"
            + json.dumps(
                {**VALID_ARTIFACT, "html": '<div id="app"></div>', "css": "", "js": ""},
                ensure_ascii=False,
            )
            + "\n```",
            ui_mode="2D",
        )

        self.assertIn("2D initial content is too sparse", requested_artifact_quality_issues(normalized, "2D"))

    def test_the_prompt_worked_example_passes_the_validator_and_the_quality_gate(self):
        normalized = normalize_response_with_artifacts(
            GENERATIVE_UI_EXECUTION_CONTRACT, ui_mode="2D"
        )

        self.assertEqual(normalized.validation_errors, [])
        self.assertTrue(normalized.has_artifact())
        self.assertEqual(requested_artifact_quality_issues(normalized, "2D"), [])


class GeneratedUiStatusDeliveryTests(unittest.TestCase):
    def test_a_failure_reaches_the_client_as_a_status_part(self):
        normalized = normalize_response_with_artifacts("比較結果はA案が優位です。", ui_mode="2D")

        payload = normalized.status_payload()

        self.assertEqual(payload, {"state": "rejected", "reason_code": "required_artifact_missing"})
        self.assertEqual(
            artifact_status_part(payload),
            {"type": "artifact_status", "status": payload},
        )

    def test_a_success_is_reported_without_interrupting_the_answer(self):
        normalized = normalize_response_with_artifacts(_artifact_block(), recover_truncated=True)

        payload = normalized.status_payload()

        self.assertEqual(payload["state"], "accepted")
        self.assertIsNone(artifact_status_part(payload))

    def test_a_status_part_survives_the_history_round_trip(self):
        parts = [
            {"type": "text", "text": "比較結果はA案が優位です。"},
            {"type": "artifact_status", "status": {"state": "failed", "reason_code": "artifact_repair_invalid"}},
        ]

        decoded = decode_message_parts(encode_message_parts(parts))

        self.assertEqual(decoded, parts)

    def test_a_successful_status_is_not_persisted_as_a_visible_part(self):
        decoded = decode_message_parts(
            [{"type": "artifact_status", "status": {"state": "accepted", "reason_code": "valid"}}]
        )

        self.assertIsNone(decoded)


class GeneratedUiTurnDeliveryTests(unittest.TestCase):
    """1ターン全体で、生成UIの失敗が配信・保存・計測に残ることを確認する。

    Verify that a generated-UI failure survives an entire turn: delivered, persisted, measured.
    """

    def _run_turn(self, streamed_answer: str, repaired_answer: str) -> tuple[Any, list[Any], Any]:
        events: list[Any] = []
        persisted = mock.Mock(return_value=None)
        job = ChatGenerationJob(
            conversation_messages=[{"role": "user", "content": "比較を生成UIで見せて"}],
            model="openai/gpt-oss-120b",
            persist_response=persisted,
            on_event=events.append,
            ui_mode="2D",
        )

        with (
            mock.patch("services.chat_generation.is_web_search_enabled", return_value=False),
            mock.patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=lambda *_args, **_kwargs: iter([streamed_answer]),
            ),
            mock.patch(
                "services.chat_generation.get_llm_response",
                return_value=repaired_answer,
            ),
        ):
            job._run()

        done_event = next(event for event in events if event.event in {"done", "incomplete"})
        return job, events, done_event

    def test_a_requested_ui_that_never_arrives_is_reported_not_silently_dropped(self):
        job, _events, done_event = self._run_turn("比較結果はA案が優位です。", "まだ文章だけです。")

        self.assertEqual(
            done_event.payload["artifact_status"],
            {"state": "failed", "reason_code": "required_artifact_missing"},
        )
        self.assertIn(
            {"type": "artifact_status", "status": done_event.payload["artifact_status"]},
            done_event.payload["parts"],
        )
        self.assertEqual(job._telemetry.artifact_status, "repair_failed")
        self.assertTrue(job._telemetry.artifact_repair_attempted)
        self.assertFalse(job._telemetry.artifact_repair_succeeded)
        self.assertEqual(job._telemetry.ui_mode, "2D")
        self.assertEqual(job._telemetry.ui_mode_decision_status, "decided")

    def test_a_repaired_ui_is_delivered_and_counted_as_repaired(self):
        job, _events, done_event = self._run_turn(
            "比較結果はA案が優位です。",
            _artifact_block(POLISHED_ARTIFACT, introduction=""),
        )

        self.assertEqual(done_event.payload["artifact_status"]["state"], "repaired")
        self.assertTrue(
            any(part["type"] == "sandbox_artifact" for part in done_event.payload["parts"])
        )
        self.assertFalse(
            any(part["type"] == "artifact_status" for part in done_event.payload["parts"])
        )
        self.assertEqual(job._telemetry.artifact_status, "valid")
        self.assertTrue(job._telemetry.artifact_repair_succeeded)


class GeneratedUiTelemetryTests(unittest.TestCase):
    def test_generated_ui_telemetry_fields_are_stable_and_keep_existing_counters(self):
        telemetry = ChatGenerationTelemetry(model="test-model")
        payload = telemetry.as_log_extra()

        self.assertEqual(payload["model"], "test-model")
        for existing_key in (
            "llm_turns",
            "tool_calls",
            "continuation_count",
            "input_limit_recoveries",
            "empty_answer_recoveries",
        ):
            with self.subTest(existing_key=existing_key):
                self.assertIn(existing_key, payload)

        for generated_ui_key in (
            "ui_mode",
            "ui_mode_decision_status",
            "explicit_ui_opt_out",
            "artifact_status",
            "artifact_reason_codes",
            "artifact_repair_attempted",
            "artifact_repair_succeeded",
            "artifact_repair_output_limited",
        ):
            with self.subTest(generated_ui_key=generated_ui_key):
                self.assertIn(generated_ui_key, payload)

        self.assertEqual(payload["artifact_status"], "not_requested")
        self.assertEqual(payload["artifact_reason_codes"], [])
        self.assertFalse(payload["artifact_repair_attempted"])
        self.assertFalse(payload["artifact_repair_succeeded"])
        self.assertFalse(payload["artifact_repair_output_limited"])

    def test_artifact_reason_codes_are_not_shared_between_telemetry_instances(self):
        first = ChatGenerationTelemetry(model="first")
        second = ChatGenerationTelemetry(model="second")

        first.artifact_reason_codes.append("artifact_validation_failed")

        self.assertEqual(first.as_log_extra()["artifact_reason_codes"], ["artifact_validation_failed"])
        self.assertEqual(second.as_log_extra()["artifact_reason_codes"], [])


if __name__ == "__main__":
    unittest.main()
