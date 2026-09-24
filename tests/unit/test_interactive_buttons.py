"""チャット標準の選択ボタン（Yes/No・単一選択・複数選択）の抽出・検証・表示契約を検証する。

Verifies extraction, validation and the display contract of the standard chat choice buttons
(yes/no, single choice, multiple select): they survive every generated-UI decision, sit beside
web-search images, and keep previously saved parts readable.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from services.chat_context import build_context_messages
from services.chat_prompt import BASE_SYSTEM_PROMPT, build_base_system_prompt
from services.generative_ui import (
    build_message_parts_context,
    decode_message_parts,
    encode_message_parts,
    normalize_response_with_artifact_retry,
    normalize_response_with_artifacts,
)
from services.interactive_buttons import (
    MAX_INTERACTIVE_BUTTON_OPTIONS,
    MAX_INTERACTIVE_BUTTONS_QUESTION_CHARS,
    InteractiveButtonsValidationError,
    validate_interactive_buttons_payload,
)
from services.message_parts_display import normalize_message_parts_for_display
from services.user_skills import build_chat_skills_context
from services.web_search_images import append_web_search_image_parts

# 品質ゲートを通る生成UI。選択ボタンとの共存と、修復後もボタンが残ることの確認に使う。
# A generated UI that passes the quality gate, used to check coexistence and repair survival.
ARTIFACT: dict[str, Any] = {
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

YES_NO = {"type": "yes_no", "question": "このまま移行を実行しますか？"}
SINGLE = {"type": "multiple_choice", "question": "どの形式でまとめますか？", "options": ["箇条書き", "表", "文章"]}
MULTIPLE = {
    "type": "multiple_select",
    "question": "レポートに含める章を選んでください",
    "options": ["概要", "費用", "リスク", "日程"],
}


def _buttons_block(payload: dict[str, Any], *, fence: str = "chatcore-buttons") -> str:
    return f"```{fence}\n{json.dumps(payload, ensure_ascii=False)}\n```"


def _artifact_block() -> str:
    return f"```chatcore-artifact\n{json.dumps(ARTIFACT, ensure_ascii=False)}\n```"


def _parts_of_type(parts: list[dict[str, Any]] | None, part_type: str) -> list[dict[str, Any]]:
    return [part for part in parts or [] if part.get("type") == part_type]


class InteractiveButtonsValidationTests(unittest.TestCase):
    def test_each_type_keeps_its_contract(self):
        self.assertEqual(validate_interactive_buttons_payload(YES_NO), YES_NO)
        self.assertEqual(validate_interactive_buttons_payload(SINGLE), SINGLE)
        self.assertEqual(validate_interactive_buttons_payload(MULTIPLE), MULTIPLE)

    def test_yes_no_ignores_options_because_the_client_shows_yes_and_no(self):
        validated = validate_interactive_buttons_payload({**YES_NO, "options": ["する", "しない"]})

        self.assertEqual(validated, YES_NO)

    def test_blank_and_duplicate_options_are_dropped_before_counting(self):
        validated = validate_interactive_buttons_payload(
            {"type": "multiple_select", "question": "選んでください", "options": [" 概要 ", "", "概要", "費用 "]}
        )

        self.assertEqual(validated["options"], ["概要", "費用"])

    def test_invalid_payloads_are_rejected(self):
        cases = {
            "unknown type": {"type": "checkbox", "question": "q", "options": ["a", "b"]},
            "missing question": {"type": "yes_no", "question": "  "},
            "question too long": {
                "type": "yes_no",
                "question": "あ" * (MAX_INTERACTIVE_BUTTONS_QUESTION_CHARS + 1),
            },
            "single choice without options": {"type": "multiple_choice", "question": "q"},
            "single choice with blank options only": {"type": "multiple_choice", "question": "q", "options": [" ", ""]},
            "multiple select with one option": {"type": "multiple_select", "question": "q", "options": ["a"]},
            "multiple select with duplicates of one option": {
                "type": "multiple_select",
                "question": "q",
                "options": ["a", "a"],
            },
            "too many options": {
                "type": "multiple_select",
                "question": "q",
                "options": [f"選択肢{index}" for index in range(MAX_INTERACTIVE_BUTTON_OPTIONS + 1)],
            },
            "non-string options": {"type": "multiple_choice", "question": "q", "options": [1, 2]},
            "not an object": ["yes_no"],
        }
        for label, payload in cases.items():
            with self.subTest(label):
                with self.assertRaises(InteractiveButtonsValidationError):
                    validate_interactive_buttons_payload(payload)

    def test_the_option_limit_itself_is_accepted(self):
        options = [f"選択肢{index}" for index in range(MAX_INTERACTIVE_BUTTON_OPTIONS)]
        validated = validate_interactive_buttons_payload(
            {"type": "multiple_select", "question": "q", "options": options}
        )

        self.assertEqual(validated["options"], options)


class InteractiveButtonsExtractionTests(unittest.TestCase):
    def test_buttons_survive_a_disabled_or_refused_generated_ui(self):
        raw = f"移行すると3列が削除されます。\n\n{_buttons_block(YES_NO)}"

        # 生成UIの Skill を切ると ui_mode は NONE、明示的な拒否として扱われる（chat_use_case）。
        # A disabled Skill arrives as ui_mode NONE plus an explicit opt-out (see chat_use_case).
        for ui_mode, opted_out in (("NONE", True), ("NONE", False), (None, False), (None, True)):
            with self.subTest(ui_mode=ui_mode, opted_out=opted_out):
                normalized = normalize_response_with_artifacts(
                    raw,
                    recover_truncated=True,
                    ui_mode=ui_mode,
                    explicit_ui_opt_out=opted_out,
                )

                self.assertEqual(normalized.text, "移行すると3列が削除されます。")
                self.assertEqual(
                    normalized.parts,
                    [
                        {"type": "text", "text": "移行すると3列が削除されます。"},
                        {"type": "interactive_buttons", "buttons": YES_NO},
                    ],
                )
                self.assertEqual(normalized.validation_errors, [])

    def test_buttons_do_not_change_the_generated_ui_status(self):
        raw = f"前置きです。\n\n{_buttons_block(SINGLE)}"

        not_requested = normalize_response_with_artifacts(raw, ui_mode="NONE")
        requested = normalize_response_with_artifacts(raw, ui_mode="2D")

        self.assertEqual(not_requested.artifact_status, "not_requested")
        self.assertEqual(requested.artifact_status, "missing")
        self.assertEqual(requested.artifact_reason_codes, ["required_artifact_missing"])
        self.assertEqual(len(_parts_of_type(requested.parts, "interactive_buttons")), 1)

    def test_invalid_block_is_hidden_without_reporting_a_generated_ui_failure(self):
        raw = f"前置きです。\n\n{_buttons_block({'type': 'multiple_select', 'question': 'q', 'options': ['a']})}"

        normalized = normalize_response_with_artifacts(raw, ui_mode="NONE")

        self.assertEqual(normalized.text, "前置きです。")
        self.assertIsNone(normalized.parts)
        self.assertEqual(normalized.validation_errors, [])
        self.assertEqual(normalized.artifact_status, "not_requested")

    def test_legacy_fence_aliases_are_still_read(self):
        for fence in ("interactive-buttons", "interactive_buttons", "chatcore-buttons json"):
            with self.subTest(fence=fence):
                normalized = normalize_response_with_artifacts(f"本文\n\n{_buttons_block(MULTIPLE, fence=fence)}")

                self.assertEqual(normalized.text, "本文")
                self.assertEqual(_parts_of_type(normalized.parts, "interactive_buttons")[0]["buttons"], MULTIPLE)

    def test_buttons_follow_a_generated_ui_in_the_same_reply(self):
        raw = f"比較しました。\n\n{_artifact_block()}\n\n{_buttons_block(SINGLE)}"

        normalized = normalize_response_with_artifacts(raw, recover_truncated=True, ui_mode="2D")

        self.assertEqual(normalized.artifact_status, "valid")
        self.assertEqual(
            [part["type"] for part in normalized.parts or []],
            ["text", "sandbox_artifact", "interactive_buttons"],
        )

    def test_buttons_only_reply_keeps_a_visible_text(self):
        normalized = normalize_response_with_artifacts(_buttons_block(YES_NO))

        self.assertEqual(normalized.text, "ボタンを選択してください。")
        self.assertEqual(
            [part["type"] for part in normalized.parts or []],
            ["text", "interactive_buttons"],
        )

    def test_repair_keeps_the_original_buttons(self):
        raw = f"比較を作ります。\n\n{_buttons_block(MULTIPLE)}"
        captured_prompts: list[str] = []

        def generate_response(messages: list[dict[str, Any]], _model: str) -> str:
            captured_prompts.append("\n".join(str(message.get("content") or "") for message in messages))
            # 修復結果に紛れたボタンは採用せず、元の回答のボタンだけを残す。
            # Buttons that slip into the repair output are ignored in favour of the original's.
            return f"比較しました。\n\n{_artifact_block()}\n\n{_buttons_block(YES_NO)}"

        normalized = normalize_response_with_artifact_retry(
            raw,
            conversation_messages=[{"role": "user", "content": "比較を生成UIで見せて"}],
            model="test-model",
            generate_response=generate_response,
            user_request="比較を生成UIで見せて",
            ui_mode="2D",
        )

        self.assertTrue(normalized.repair_attempted)
        self.assertEqual(normalized.artifact_status, "valid")
        self.assertEqual(
            [part["type"] for part in normalized.parts or []],
            ["text", "sandbox_artifact", "interactive_buttons"],
        )
        self.assertEqual(_parts_of_type(normalized.parts, "interactive_buttons")[0]["buttons"], MULTIPLE)
        self.assertNotIn("chatcore-buttons", normalized.text)
        self.assertNotIn("chatcore-buttons", captured_prompts[0])

    def test_retry_without_a_requested_ui_keeps_buttons(self):
        normalized = normalize_response_with_artifact_retry(
            f"本文\n\n{_buttons_block(SINGLE)}",
            conversation_messages=[],
            model="test-model",
            generate_response=lambda _messages, _model: self.fail("no repair expected"),
            ui_mode="NONE",
            explicit_ui_opt_out=True,
        )

        self.assertEqual(_parts_of_type(normalized.parts, "interactive_buttons")[0]["buttons"], SINGLE)


class InteractiveButtonsDisplayContractTests(unittest.TestCase):
    def test_buttons_sit_beside_web_search_images(self):
        parts = [
            {"type": "text", "text": "明月院と東慶寺を紹介します。どちらを詳しく知りたいですか。"},
            {"type": "interactive_buttons", "buttons": {**SINGLE, "options": ["明月院", "東慶寺"]}},
        ]

        placed = append_web_search_image_parts(
            parts,
            {
                "url": "https://example.com/images/meigetsuin.jpg",
                "alt": "明月院の写真",
                "source_url": "https://example.com/meigetsuin",
                "placement": "after_subject",
                "placement_anchor": "明月院",
            },
        )

        self.assertEqual(
            [part["type"] for part in placed or []],
            ["text", "web_search_image", "text", "interactive_buttons"],
        )
        self.assertEqual(normalize_message_parts_for_display(placed), placed)

    def test_display_contract_keeps_images_next_to_buttons(self):
        image = {
            "type": "web_search_image",
            "image": {"url": "https://example.com/a.jpg", "alt": "写真", "source_url": "https://example.com/a"},
        }
        parts = [
            {"type": "text", "text": "本文"},
            image,
            {"type": "interactive_buttons", "buttons": YES_NO},
        ]

        self.assertEqual(normalize_message_parts_for_display(parts), parts)


class InteractiveButtonsStoredPartsTests(unittest.TestCase):
    def test_previously_saved_parts_still_decode(self):
        # 変更前の保存形式（yes_no に options が残っていた形も含む）をそのまま読めること。
        # Parts stored before this change, including a yes_no that still carried options.
        stored = json.dumps(
            [
                {"type": "text", "text": "確認です。"},
                {"type": "interactive_buttons", "buttons": {**YES_NO, "options": ["Yes", "No"]}},
                {"type": "interactive_buttons", "buttons": SINGLE},
            ],
            ensure_ascii=False,
        )

        decoded = decode_message_parts(stored)

        self.assertEqual(
            decoded,
            [
                {"type": "text", "text": "確認です。"},
                {"type": "interactive_buttons", "buttons": YES_NO},
                {"type": "interactive_buttons", "buttons": SINGLE},
            ],
        )

    def test_multiple_select_round_trips_and_invalid_parts_are_dropped(self):
        encoded = encode_message_parts(
            [
                {"type": "text", "text": "選んでください。"},
                {"type": "interactive_buttons", "buttons": MULTIPLE},
                {"type": "interactive_buttons", "buttons": {"type": "multiple_select", "question": "q"}},
            ]
        )

        self.assertEqual(
            decode_message_parts(encoded),
            [
                {"type": "text", "text": "選んでください。"},
                {"type": "interactive_buttons", "buttons": MULTIPLE},
            ],
        )

    def test_later_turns_see_the_question_type_and_options(self):
        context = build_message_parts_context([{"type": "interactive_buttons", "buttons": MULTIPLE}])

        self.assertIn('<interactive_buttons type="multiple_select">', context)
        self.assertIn("<question>レポートに含める章を選んでください</question>", context)
        self.assertIn("<options>概要 | 費用 | リスク | 日程</options>", context)


class InteractiveButtonsPromptContractTests(unittest.TestCase):
    def test_prompt_describes_every_type_and_the_enforced_limits(self):
        section = BASE_SYSTEM_PROMPT.split("## Choice buttons\n", 1)[1].split("\n## ", 1)[0]

        self.assertIn("```chatcore-buttons", section)
        for button_type in ("yes_no", "multiple_choice", "multiple_select"):
            with self.subTest(button_type=button_type):
                self.assertIn(f'"type":"{button_type}"', section)
        self.assertIn(f"2 to {MAX_INTERACTIVE_BUTTON_OPTIONS} short", section)
        self.assertIn(f"at most {MAX_INTERACTIVE_BUTTONS_QUESTION_CHARS} characters", section)

    def test_prompt_example_passes_the_validator(self):
        section = BASE_SYSTEM_PROMPT.split("## Choice buttons\n", 1)[1].split("\n## ", 1)[0]
        example = section.split("```chatcore-buttons\n", 1)[1].split("\n```", 1)[0]

        validate_interactive_buttons_payload(json.loads(example))

    def test_buttons_stay_in_the_prompt_when_the_generated_ui_skill_is_off(self):
        skills_context = build_chat_skills_context(
            [],
            {"id": 1, "generative_ui_skill_enabled": False},
            locale="ja",
        )
        skills_prompt, enabled = skills_context.prompt, skills_context.generative_ui_enabled
        messages = build_context_messages(
            base_system_prompt=build_base_system_prompt(locale="ja"),
            user_profile_prompt=None,
            task_prompt=None,
            room_summary="",
            memory_facts=[],
            recent_messages=[{"role": "user", "content": "どれにするか選ばせて"}],
            user_skills_prompt=skills_prompt,
            generative_ui_enabled=enabled,
        )

        self.assertFalse(enabled)
        self.assertIn("## Choice buttons", "\n".join(str(message["content"]) for message in messages))


if __name__ == "__main__":
    unittest.main()
