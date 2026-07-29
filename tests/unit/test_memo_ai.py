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


if __name__ == "__main__":
    unittest.main()
