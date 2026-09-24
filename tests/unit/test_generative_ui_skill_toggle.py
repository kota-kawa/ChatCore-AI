"""生成UIの Skill を切ったとき、組み立てたプロンプトに生成UIの指示が一切残らないことを検証する。

Verifies that turning the Generative UI Skill off leaves no Generative UI instruction anywhere in
the assembled prompt, and that an enabled Skill gives guests and signed-in users the same text.
"""

import unittest

from services.chat_context import build_context_messages
from services.chat_prompt import build_base_system_prompt
from services.user_skills import (
    GENERATIVE_UI_EXECUTION_CONTRACT,
    GENERATIVE_UI_SKILL_INSTRUCTIONS,
    build_chat_skills_context,
)

_GENERATIVE_UI_TERMS = ("UI_MODE", "Artifact", "chatcore-artifact", "generated UI", "generative UI")


def _assembled_prompt(user):
    skills_context = build_chat_skills_context([], user, locale="ja")
    messages = build_context_messages(
        base_system_prompt=build_base_system_prompt(locale="ja"),
        user_profile_prompt=None,
        task_prompt=None,
        room_summary="",
        memory_facts=[],
        recent_messages=[{"role": "user", "content": "グラフで見せて"}],
        user_skills_prompt=skills_context.prompt,
        generative_ui_enabled=skills_context.generative_ui_enabled,
    )
    return "\n".join(str(message["content"]) for message in messages)


class GenerativeUiSkillToggleTests(unittest.TestCase):
    def test_disabled_skill_leaves_no_generative_ui_instruction(self):
        prompt = _assembled_prompt({"id": 1, "generative_ui_skill_enabled": False})
        for term in _GENERATIVE_UI_TERMS:
            with self.subTest(term=term):
                self.assertNotIn(term, prompt)

    def test_enabled_skill_carries_both_the_instructions_and_the_contract(self):
        prompt = _assembled_prompt({"id": 1, "generative_ui_skill_enabled": True})
        self.assertIn(GENERATIVE_UI_SKILL_INSTRUCTIONS, prompt)
        self.assertIn(GENERATIVE_UI_EXECUTION_CONTRACT, prompt)

    def test_guests_get_the_same_generative_ui_prompt_as_signed_in_users(self):
        self.assertEqual(
            _assembled_prompt(None),
            _assembled_prompt({"id": 1, "generative_ui_skill_enabled": True}),
        )

    def test_decision_rules_and_output_format_are_not_duplicated(self):
        # 判定規則は Skill の指示、出力形式は実行契約だけが持つ。
        # Decision rules belong to the Skill, the output format to the contract only.
        self.assertNotIn("Decision order", GENERATIVE_UI_EXECUTION_CONTRACT)
        self.assertNotIn("```chatcore-artifact", GENERATIVE_UI_SKILL_INSTRUCTIONS)
        self.assertNotIn('id="app"', GENERATIVE_UI_SKILL_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
