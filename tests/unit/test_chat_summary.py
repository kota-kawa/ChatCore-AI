import unittest
from unittest.mock import patch

from services.chat_summary import build_room_summary_text
from services.llm import CLAUDE_DEFAULT_MODEL, LlmConfigurationError


def _long_history() -> list[dict[str, str]]:
    # 要約対象が発生する程度に長い履歴を作る
    # Build a history long enough to produce archived messages
    messages: list[dict[str, str]] = []
    for index in range(16):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"message-{index}"})
    return messages


# 日本語: ルーム要約が選択中モデルで生成され、失敗時は決定的方式へ退避することを検証するクラス。
# English: Test class asserting the room summary uses the conversation's model and
# falls back to the deterministic summary when that call fails.
class ChatSummaryTestCase(unittest.TestCase):
    # 日本語: 要約は会話で選択されているモデルで行われることを検証します。
    # English: Verify summarization runs on the conversation's selected model.
    def test_summary_uses_the_conversation_model(self):
        with patch(
            "services.chat_summary.get_llm_response",
            return_value="GOAL: ship the feature\nFACTS: the branch is main",
        ) as mocked:
            summary, archived_count = build_room_summary_text(
                _long_history(), model=CLAUDE_DEFAULT_MODEL
            )

        self.assertEqual(mocked.call_args.args[1], CLAUDE_DEFAULT_MODEL)
        self.assertEqual(archived_count, 4)
        self.assertIn("<conversation_summary>", summary)
        self.assertIn("GOAL: ship the feature", summary)
        # 抜粋方式の見出しではなく、モデルの要約本文が入ること
        # The model's summary body replaces the excerpt sections
        self.assertNotIn("<user_points>", summary)

    # 日本語: モデル呼び出しが失敗した場合、決定的な抜粋要約へフォールバックすることを検証します。
    # English: Verify a failed model call falls back to the deterministic excerpt summary.
    def test_falls_back_to_excerpt_summary_on_failure(self):
        with patch(
            "services.chat_summary.get_llm_response",
            side_effect=LlmConfigurationError("no key"),
        ):
            summary, archived_count = build_room_summary_text(
                _long_history(), model=CLAUDE_DEFAULT_MODEL
            )

        self.assertEqual(archived_count, 4)
        self.assertIn("<conversation_summary>", summary)
        self.assertIn("message-0", summary)

    # 日本語: モデル未指定時はLLMを呼ばず決定的方式を使うことを検証します。
    # English: Verify no model means no LLM call and the deterministic summary is used.
    def test_without_a_model_no_llm_call_is_made(self):
        with patch("services.chat_summary.get_llm_response") as mocked:
            summary, archived_count = build_room_summary_text(_long_history())

        mocked.assert_not_called()
        self.assertEqual(archived_count, 4)
        self.assertIn("message-0", summary)

    # 日本語: 要約対象がない短い履歴では何も生成しないことを検証します。
    # English: Verify a short history produces no summary at all.
    def test_short_history_produces_no_summary(self):
        with patch("services.chat_summary.get_llm_response") as mocked:
            summary, archived_count = build_room_summary_text(
                [{"role": "user", "content": "hello"}], model=CLAUDE_DEFAULT_MODEL
            )

        mocked.assert_not_called()
        self.assertEqual((summary, archived_count), ("", 0))

    # 日本語: 空の要約が返った場合も抜粋方式へ退避することを検証します。
    # English: Verify an empty model summary also falls back to the excerpt summary.
    def test_empty_model_summary_falls_back(self):
        with patch("services.chat_summary.get_llm_response", return_value="   "):
            summary, _ = build_room_summary_text(
                _long_history(), model=CLAUDE_DEFAULT_MODEL
            )

        self.assertIn("message-0", summary)


if __name__ == "__main__":
    unittest.main()
