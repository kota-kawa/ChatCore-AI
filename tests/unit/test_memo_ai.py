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

    # 日本語: メモ本文だけを言語判定対象として、共通の応答言語ポリシーが適用されることを検証します。
    # English: Verify the shared policy determines title language from the memo body alone.
    def test_suggest_title_uses_memo_body_as_the_language_source(self):
        with patch(
            "services.memo_ai.get_llm_response",
            return_value='{"title": "Meeting notes"}',
        ) as mock_response:
            suggest_title("English notes with 日本語の要望", locale="en")

        messages = mock_response.call_args.args[0]
        system_content = messages[0]["content"]
        self.assertIn("the part that states the user's request or instruction", system_content)
        self.assertIn("larger share", system_content)
        self.assertIn("saved interface language (English)", system_content)
        self.assertIn("memo body alone", system_content)
        self.assertIn("must not influence the title language", system_content)
        self.assertEqual(
            messages[1],
            {
                "role": "user",
                "content": "<memo_body>\nEnglish notes with 日本語の要望\n</memo_body>",
            },
        )


if __name__ == "__main__":
    unittest.main()
