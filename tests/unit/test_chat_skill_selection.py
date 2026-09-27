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
        self.assertFalse(result.context.memo_tools_enabled)

    def test_unconditional_response_style_survives_when_the_rest_of_a_skill_is_irrelevant(self):
        style = "いつもは簡潔で明確な日本語で回答してください。質問の主旨に直接答えてください。"
        instructions = f"{style}\n\nOrchidの公開前確認は火曜日に行います。"
        context = _context(
            user_skills=[{"id": 2200, "name": "全体の回答スタイルと背景", "instructions": instructions}],
            ui_enabled=False,
            memo_enabled=False,
        )

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "オンボーディングメモを検索してください"}],
            "model",
            llm_json_response=Mock(return_value=_decision()),
        )

        self.assertEqual(result.telemetry["selected_skill_ids"], [2200])
        self.assertEqual(result.telemetry["always_applicable_skill_ids"], [2200])
        self.assertIn(style, result.context.prompt or "")
        self.assertNotIn("Orchid", result.context.prompt or "")

    def test_task_scoped_skill_is_not_retained_as_a_global_response_preference(self):
        context = _context(
            user_skills=[
                {
                    "id": 2202,
                    "name": "家族ゲーム",
                    "instructions": "家族ゲームの計画にだけ適用します。いつも準備物を表にしてください。",
                }
            ],
            ui_enabled=False,
            memo_enabled=False,
        )

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "HTTP 401と403の違いを説明して"}],
            "model",
            llm_json_response=Mock(return_value=_decision()),
        )

        self.assertIsNone(result.context.prompt)
        self.assertEqual(result.telemetry["always_applicable_skill_ids"], [])

    def test_global_prefix_does_not_retain_topic_scoped_response_preferences(self):
        context = _context(
            user_skills=[
                {"id": 2203, "name": "障害報告", "instructions": "Always answer bug report questions in a table."},
                {"id": 2204, "name": "旅行計画", "instructions": "いつも旅行計画の回答は表にしてください。"},
                {"id": 2205, "name": "Orchid", "instructions": "Always answer in Japanese when discussing Orchid."},
                {"id": 2207, "name": "障害報告", "instructions": "Always answer in Japanese for bug reports."},
                {"id": 2210, "name": "全障害報告", "instructions": "Always answer in Japanese for all bug reports."},
                {"id": 2216, "name": "利用者の障害報告", "instructions": "Always answer in Japanese for all user bug reports."},
                {"id": 2208, "name": "会議", "instructions": "いつも会議のときは回答を箇条書きにしてください。"},
            ],
            ui_enabled=False,
            memo_enabled=False,
        )

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "HTTP 401と403の違いを説明して"}],
            "model",
            llm_json_response=Mock(return_value=_decision()),
        )

        self.assertIsNone(result.context.prompt)
        self.assertEqual(result.telemetry["always_applicable_skill_ids"], [])

    def test_all_answers_prefix_is_kept_when_it_has_no_topic_scope(self):
        context = _context(
            user_skills=[
                {"id": 2206, "name": "全体の回答スタイル", "instructions": "すべての回答は簡潔な日本語でお願いします。"},
                {"id": 2209, "name": "日本語の回答スタイル", "instructions": "いつも日本語の回答をしてください。"},
                {"id": 2211, "name": "全質問の回答スタイル", "instructions": "Always answer in Japanese for all questions."},
                {"id": 2212, "name": "全回答の形式", "instructions": "Always answer in Japanese for all answers."},
                {"id": 2213, "name": "全応答の形式", "instructions": "Always answer in Japanese for all responses."},
                {"id": 2214, "name": "全依頼の形式", "instructions": "Always answer in Japanese for all requests."},
                {"id": 2215, "name": "利用者向けの形式", "instructions": "Always answer in Japanese for all users."},
                {"id": 2217, "name": "全回答単数形", "instructions": "For every answer, use Japanese."},
                {"id": 2218, "name": "全応答単数形", "instructions": "For every response, use Japanese."},
                {"id": 2219, "name": "利用者の全質問", "instructions": "Always answer in Japanese for all user questions."},
                {"id": 2220, "name": "全利用者質問の形式", "instructions": "For all user questions, answer in Japanese."},
                {"id": 2221, "name": "全質問の形式", "instructions": "Always answer questions in Japanese."},
                {"id": 2222, "name": "全質問への回答形式", "instructions": "Always answer all questions in Japanese."},
            ],
            ui_enabled=False,
            memo_enabled=False,
        )

        result = select_chat_skills(
            context,
            [{"role": "user", "content": "予定をまとめてください"}],
            "model",
            llm_json_response=Mock(return_value=_decision()),
        )

        self.assertEqual(
            result.telemetry["always_applicable_skill_ids"],
            [2206, 2209, 2211, 2212, 2213, 2214, 2215, 2217, 2218, 2219, 2220, 2221, 2222],
        )
        self.assertIn("すべての回答は簡潔な日本語でお願いします。", result.context.prompt or "")
        self.assertIn("いつも日本語の回答をしてください。", result.context.prompt or "")

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
