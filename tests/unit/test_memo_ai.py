import unittest
from unittest.mock import patch

from services.llm import LIGHTWEIGHT_TASK_MODEL
from services.memo_ai import suggest_title


class MemoAiTestCase(unittest.TestCase):
    def test_suggest_title_uses_lightweight_model(self):
        with patch(
            "services.memo_ai.get_llm_response",
            return_value='{"title": "会議メモ"}',
        ) as mock_response:
            result = suggest_title("来週の会議では予算と日程を確認する。")

        self.assertEqual(result, {"title": "会議メモ"})
        self.assertEqual(mock_response.call_args.args[1], LIGHTWEIGHT_TASK_MODEL)

    # 日本語: メモタイトル提案にも混在言語入力の共通判定順序が渡されることを検証します。
    # English: Verify the shared mixed-language decision order is included for memo title suggestions.
    def test_suggest_title_includes_shared_response_language_policy(self):
        with patch(
            "services.memo_ai.get_llm_response",
            return_value='{"title": "Meeting notes"}',
        ) as mock_response:
            suggest_title("English notes with 日本語の要望", locale="en")

        system_content = mock_response.call_args.args[0][0]["content"]
        self.assertIn("the part that states the user's request or instruction", system_content)
        self.assertIn("larger share", system_content)
        self.assertIn("saved interface language (English)", system_content)


if __name__ == "__main__":
    unittest.main()
