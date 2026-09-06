import unittest

from services.chat_context import estimate_token_count
from services.chat_context_recovery import (
    RECOVERY_HISTORY_TOKEN_BUDGET,
    build_recovery_base_messages,
)


class ChatContextRecoveryTestCase(unittest.TestCase):
    def test_keeps_latest_exchange_and_drops_tools_and_optional_context(self):
        recent = [
            {"role": "user", "content": "Compare the two storage options."},
            {"role": "assistant", "content": "A is faster; B needs less space."},
            {"role": "user", "content": "And for my use case?"},
        ]
        messages = [
            {"role": "system", "content": "Base guidance"},
            {"role": "system", "content": "<turn_state>old state</turn_state>"},
            {"role": "system", "content": "Optional project instructions"},
            {"role": "user", "content": "An older topic"},
            {"role": "assistant", "content": "An older answer"},
            recent[0],
            {"role": "assistant", "content": "Searching", "tool_calls": [{"id": "old"}]},
            {"role": "tool", "content": "Raw evidence", "tool_call_id": "old"},
            *recent[1:],
        ]

        recovered = build_recovery_base_messages(messages)

        self.assertEqual(recovered, [messages[0], *recent])
        self.assertEqual(len(messages), 10)

    def test_long_previous_exchange_cannot_displace_either_message(self):
        for question, answer in (
            ("Compare A and B. " * 3000, "A is faster. " * 3000),
            ("Compare A and B.", "A is faster. " * 3000),
        ):
            with self.subTest(question_length=len(question)):
                messages = [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": "Which fits the constraints?"},
                ]

                recovered = build_recovery_base_messages(messages)

                self.assertEqual([m["role"] for m in recovered], ["user", "assistant", "user"])
                self.assertTrue(recovered[0]["content"].startswith("Compare A and B."))
                self.assertTrue(recovered[1]["content"].startswith("A is faster."))
                self.assertEqual(recovered[-1], messages[-1])
                self.assertLessEqual(
                    sum(estimate_token_count(m["content"]) for m in recovered[:-1]),
                    RECOVERY_HISTORY_TOKEN_BUDGET,
                )

    def test_first_turn_preserves_input_verbatim(self):
        message = {"role": "user", "content": "<attached_files>data</attached_files>\n\n  Fix this code.\n"}
        self.assertEqual(build_recovery_base_messages([message]), [message])

    def test_explicit_topic_change_and_correction_are_not_rewritten(self):
        for latest in ("New topic: explain recursion.", "No, compare the second and third options."):
            with self.subTest(latest=latest):
                messages = [
                    {"role": "user", "content": "Compare three storage options."},
                    {"role": "assistant", "content": "A and B differ in cost."},
                    {"role": "user", "content": latest},
                ]
                self.assertEqual(build_recovery_base_messages(messages), messages)

    def test_reference_and_state_blocks_cannot_become_base_guidance(self):
        messages = [
            {"role": "system", "content": "<selected_reference_context>raw data"},
            {"role": "system", "content": "<web_search_context>raw results"},
            {"role": "system", "content": "<turn_state>old state"},
            {"role": "system", "content": "Base guidance"},
            {"role": "user", "content": "Question"},
        ]
        self.assertEqual(build_recovery_base_messages(messages), messages[-2:])
