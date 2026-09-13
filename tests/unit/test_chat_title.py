import unittest
from unittest.mock import MagicMock

from services.chat_title import (
    build_initial_title_candidates,
    generate_chat_room_title,
)
from services.llm import LIGHTWEIGHT_TASK_MODEL


# 日本語: チャットルームタイトルの自動生成ロジックをテストするクラス。
# English: Test class for automatic chat room title generation logic.
class ChatTitleTestCase(unittest.TestCase):
    # 日本語: LLMから返ってきたJSONレスポンスが正しくパースされてタイトルとして取得されることを検証します。
    # English: Verify that the LLM JSON response is correctly parsed and returned as the room title.
    def test_generate_chat_room_title_parses_json_response(self):
        # 日本語: LLMがJSONタイトルを返すケースをシミュレート
        # English: Simulate the LLM returning a JSON title string
        llm_response_getter = MagicMock(return_value='{"title": "Python学習計画"}')
        title = generate_chat_room_title(
            "Pythonの学習計画を作って",
            "3週間の計画を提案します。",
            llm_response_getter=llm_response_getter,
        )

        self.assertEqual(title, "Python学習計画")
        self.assertEqual(llm_response_getter.call_args.args[1], LIGHTWEIGHT_TASK_MODEL)

    # 日本語: タイトル生成にも混在言語入力の共通判定順序が渡されることを検証します。
    # English: Verify the shared mixed-language decision order is included for title generation.
    def test_generate_chat_room_title_includes_shared_response_language_policy(self):
        llm_response_getter = MagicMock(return_value='{"title": "Project plan"}')

        generate_chat_room_title(
            "Please review this. 要点は日本語で",
            "承知しました。",
            locale="en",
            llm_response_getter=llm_response_getter,
        )

        system_content = llm_response_getter.call_args.args[0][0]["content"]
        self.assertIn("the part that states the user's request or instruction", system_content)
        self.assertIn("larger share", system_content)
        self.assertIn("saved interface language (English)", system_content)

    # 日本語: タスク起動リクエストのセットアップ情報（タスク名・状況）が初期タイトル候補リストに含まれることを検証します。
    # English: Verify that task setup info (task name and context) is included in the initial title candidates list.
    def test_build_initial_title_candidates_includes_task_setup(self):
        candidates = build_initial_title_candidates(
            "【タスク】メール返信\n【状況・作業環境】採用面接の日程調整",
            task_launch_request={
                "task": "メール返信",
                "setup_info": "採用面接の日程調整",
            },
        )

        # 日本語: デフォルトタイトル・タスク名・状況がすべて候補として含まれることを確認
        # English: Confirm that default title, task name, and context are all included as candidates
        self.assertIn("新規チャット", candidates)
        self.assertIn("採用面接の日程調整", candidates)
        self.assertIn("メール返信", candidates)

if __name__ == "__main__":
    unittest.main()
