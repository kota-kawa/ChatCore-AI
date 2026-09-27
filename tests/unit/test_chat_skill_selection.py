import json
import unittest
from unittest.mock import Mock, patch

from services.chat_skill_selection import select_chat_skills
from services.user_skills import (
    GENERATIVE_UI_SYSTEM_SKILL_ID,
    MEMO_TOOLS_SYSTEM_SKILL_ID,
    build_chat_skills_context,
)


def _context(*, user_skills=None, ui_enabled=True, memo_enabled=True):
    return build_chat_skills_context(
        list(user_skills or []),
        {
            "id": 42,
            "generative_ui_skill_enabled": ui_enabled,
            "memo_tools_skill_enabled": memo_enabled,
        },
        locale="ja",
        workspace_tools_available=True,
    )


def _decision(ids=(), *, uncertain=False, ui_mode="NONE"):
    return json.dumps(
        {"selected_skill_ids": list(ids), "uncertain": uncertain, "ui_mode": ui_mode}
    )


class ChatSkillSelectionTests(unittest.TestCase):
    def test_json_decoder_limits_fall_back_without_failing_the_chat(self):
        responses = (
            '{"selected_skill_ids":[' + "1" * 5000 + '],"uncertain":false,"ui_mode":"NONE"}',
            "[" * 20_000 + "0" + "]" * 20_000,
        )
        for raw_response in responses:
            with self.subTest(prefix=raw_response[:30]):
                context = _context()
                result = select_chat_skills(
                    context, [{"role": "user", "content": "こんにちは"}], "model",
                    llm_json_response=Mock(return_value=raw_response),
                )
                self.assertEqual(result.telemetry["reason"], "invalid_response")
                self.assertTrue(result.telemetry["fallback"])
                self.assertTrue(result.context.memo_tools_enabled)
                self.assertTrue(result.context.generative_ui_selected)
                self.assertIsNone(result.ui_mode)

    def test_uses_same_model_and_passes_full_skill_bodies_as_quoted_json_data(self):
        instructions = "\n".join(["常に結論を先に書く"] + ["確認文"] * 400)
        context = _context(user_skills=[{"id": 12, "name": "回答方針", "instructions": instructions}])
        invoke = Mock(return_value=_decision([12]))

        result = select_chat_skills(
            context,
            [
                {"role": "system", "content": "secret system prompt"},
                {"role": "tool", "content": "tool result"},
                {"role": "assistant", "content": "前の回答"},
                {"role": "user", "content": "今回の質問"},
            ],
            "chosen-conversation-model",
            project_instructions="このプロジェクトでは日本語を使う",
            task_prompt="確認して回答する",
            llm_json_response=invoke,
        )

        invoke.assert_called_once()
        messages, model_name = invoke.call_args.args
        self.assertEqual(model_name, "chosen-conversation-model")
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        payload_text = messages[1]["content"].split("\n", 1)[1]
        payload = json.loads(payload_text)
        self.assertEqual(
            payload["conversation_messages"],
            [
                {"role": "assistant", "content": "前の回答"},
                {"role": "user", "content": "今回の質問"},
            ],
        )
        self.assertEqual(payload["project_instructions"], "このプロジェクトでは日本語を使う")
        self.assertEqual(payload["task_instructions"], "確認して回答する")
        self.assertEqual(payload["candidates"][-1]["instructions"], instructions)
        self.assertIn("## 回答方針", result.context.prompt or "")
        self.assertNotIn(instructions, json.dumps(result.telemetry, ensure_ascii=False))
        self.assertGreaterEqual(result.telemetry["duration_ms"], 0)

    def test_uses_custom_prompt_builder_for_the_selected_subset(self):
        builder_calls = []

        def prompt_builder(skills):
            builder_calls.append([skill["id"] for skill in skills])
            return ",".join(skill["name"] for skill in skills) or None

        context = build_chat_skills_context(
            [{"id": 8, "name": "個人", "instructions": "いつも短くする"}],
            {"id": 42, "generative_ui_skill_enabled": False},
            locale="ja",
            prompt_builder=prompt_builder,
        )

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "要点だけ"}],
            "model",
            llm_json_response=Mock(return_value=_decision([8])),
        )

        self.assertEqual(builder_calls[0], [8])
        self.assertEqual(builder_calls[1], [8])
        self.assertEqual(result.context.prompt, "個人")

    def test_zero_eligible_candidates_skips_model_call(self):
        context = _context(ui_enabled=False, memo_enabled=False)
        invoke = Mock()

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "こんにちは"}],
            "model",
            llm_json_response=invoke,
        )

        invoke.assert_not_called()
        self.assertIs(result.context, context)
        self.assertEqual(result.ui_mode, "NONE")
        self.assertEqual(result.telemetry["reason"], "no_candidates")

    def test_empty_selection_keeps_none_mode_and_does_not_mark_ui_selected(self):
        context = _context(user_skills=[{"id": 3, "name": "個人", "instructions": "専門用語を避ける"}])

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "短く説明して"}],
            "model",
            llm_json_response=Mock(return_value=_decision()),
        )

        self.assertEqual(result.ui_mode, "NONE")
        self.assertIsNone(result.context.prompt)
        self.assertTrue(result.context.generative_ui_enabled)
        self.assertFalse(result.context.generative_ui_selected)

    def test_consistent_three_dimensional_decision_selects_ui_skill(self):
        context = _context()

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "惑星を回転して見られる3Dモデルにして"}],
            "model",
            llm_json_response=Mock(
                return_value=_decision([GENERATIVE_UI_SYSTEM_SKILL_ID], ui_mode="3D")
            ),
        )

        self.assertEqual(result.ui_mode, "3D")
        self.assertTrue(result.context.generative_ui_enabled)
        self.assertTrue(result.context.generative_ui_selected)
        self.assertIn("## 生成UI", result.context.prompt or "")

    def test_invalid_id_or_inconsistent_ui_falls_back_without_inference(self):
        context = _context(user_skills=[{"id": 5, "name": "個人", "instructions": "簡潔に"}])
        responses = (
            "not JSON",
            _decision([999]),
            _decision([GENERATIVE_UI_SYSTEM_SKILL_ID], ui_mode="NONE"),
            _decision([5], ui_mode="3D"),
        )

        for response in responses:
            with self.subTest(response=response):
                result = select_chat_skills(
                    context,
                    [{"role": "user", "content": "説明して"}],
                    "model",
                    llm_json_response=Mock(return_value=response),
                )

                self.assertTrue(result.telemetry["fallback"])
                self.assertEqual(result.telemetry["reason"], "invalid_response")
                self.assertIsNone(result.ui_mode)
                self.assertTrue(result.context.generative_ui_selected)
                self.assertTrue(result.context.memo_tools_enabled)
                self.assertIn("## 個人", result.context.prompt or "")

    def test_uncertainty_uses_all_eligible_skills_and_does_not_choose_ui_mode(self):
        context = _context(user_skills=[{"id": 6, "name": "個人", "instructions": "丁寧に"}])

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "これをお願い"}],
            "model",
            llm_json_response=Mock(
                return_value=_decision([6], uncertain=True, ui_mode="NONE")
            ),
        )

        self.assertTrue(result.telemetry["fallback"])
        self.assertEqual(result.telemetry["reason"], "uncertain")
        self.assertIsNone(result.ui_mode)
        self.assertEqual(
            result.telemetry["selected_skill_ids"],
            [GENERATIVE_UI_SYSTEM_SKILL_ID, MEMO_TOOLS_SYSTEM_SKILL_ID, 6],
        )

    def test_explicit_ui_opt_out_removes_ui_from_success_and_fallback(self):
        context = _context(user_skills=[{"id": 9, "name": "個人", "instructions": "丁寧に"}])
        invoke = Mock(return_value=_decision([GENERATIVE_UI_SYSTEM_SKILL_ID], ui_mode="2D"))

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "文章だけで図の説明をして"}],
            "model",
            llm_json_response=invoke,
            generative_ui_forbidden=True,
        )

        self.assertTrue(result.telemetry["fallback"])
        self.assertEqual(result.ui_mode, "NONE")
        self.assertTrue(result.context.generative_ui_enabled)
        self.assertFalse(result.context.generative_ui_selected)
        self.assertNotIn("## 生成UI", result.context.prompt or "")
        self.assertIn("## メモ", result.context.prompt or "")
        self.assertIn("## 個人", result.context.prompt or "")

    def test_full_candidate_over_budget_skips_call_and_falls_back(self):
        context = _context(user_skills=[{"id": 17, "name": "長いSkill", "instructions": "長文 " * 100}])
        invoke = Mock()
        with patch("services.chat_skill_selection.get_available_input_tokens", return_value=8):
            result = select_chat_skills(
                context,
                [{"role": "user", "content": "適用して"}],
                "model",
                llm_json_response=invoke,
            )

        invoke.assert_not_called()
        self.assertEqual(result.telemetry["reason"], "overflow")
        self.assertEqual(result.telemetry["input_budget_tokens"], 8)
        self.assertGreater(result.telemetry["input_tokens"], 8)
        self.assertIsNone(result.ui_mode)
        self.assertIn("## 長いSkill", result.context.prompt or "")

    def test_llm_failure_metadata_never_contains_exception_text(self):
        context = _context(user_skills=[{"id": 22, "name": "秘匿Skill", "instructions": "do not log this body"}])

        def fail(_messages, _model):
            raise RuntimeError("secret provider response and API key")

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "質問"}],
            "model",
            llm_json_response=fail,
        )

        self.assertEqual(result.telemetry["reason"], "llm_error")
        self.assertTrue(result.telemetry["fallback"])
        telemetry = json.dumps(result.telemetry, ensure_ascii=False)
        self.assertNotIn("secret provider response", telemetry)
        self.assertNotIn("do not log this body", telemetry)

    def test_structured_event_contains_selection_metadata_only(self):
        private_body = "private skill source should never be logged"
        context = _context(user_skills=[{"id": 24, "name": "個人", "instructions": private_body}])
        with patch("services.chat_skill_selection.logger.info") as log_event:
            select_chat_skills(
                context,
                [{"role": "user", "content": "質問本文もログに入れない"}],
                "model",
                llm_json_response=Mock(return_value=_decision([24])),
            )

        log_event.assert_called_once()
        self.assertEqual(log_event.call_args.args, ("Chat Skill selection completed",))
        extra = log_event.call_args.kwargs["extra"]
        self.assertEqual(extra["event"], "skill_selection")
        self.assertIn("duration_ms", extra)
        self.assertIn("selected_skill_ids", extra)
        self.assertNotIn(private_body, json.dumps(extra, ensure_ascii=False))
        self.assertNotIn("質問本文", json.dumps(extra, ensure_ascii=False))

    def test_disabling_ui_setting_allows_only_none_mode(self):
        context = _context(
            user_skills=[{"id": 23, "name": "個人", "instructions": "丁寧に"}],
            ui_enabled=False,
        )

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "3Dの太陽系を表示して"}],
            "model",
            llm_json_response=Mock(return_value=_decision([23], ui_mode="3D")),
        )

        self.assertTrue(result.telemetry["fallback"])
        self.assertEqual(result.ui_mode, "NONE")
        self.assertFalse(result.context.generative_ui_enabled)
        self.assertFalse(result.context.generative_ui_selected)


if __name__ == "__main__":
    unittest.main()
