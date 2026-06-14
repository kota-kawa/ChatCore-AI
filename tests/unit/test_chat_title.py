import unittest
from unittest.mock import patch

from services.chat_title import (
    build_initial_title_candidates,
    generate_chat_room_title,
    maybe_auto_title_chat_room,
)


# 日本語: チャットルームタイトルの自動生成ロジックをテストするクラス。
# English: Test class for automatic chat room title generation logic.
class ChatTitleTestCase(unittest.TestCase):
    # 日本語: LLMから返ってきたJSONレスポンスが正しくパースされてタイトルとして取得されることを検証します。
    # English: Verify that the LLM JSON response is correctly parsed and returned as the room title.
    def test_generate_chat_room_title_parses_json_response(self):
        # 日本語: LLMがJSONタイトルを返すケースをシミュレート
        # English: Simulate the LLM returning a JSON title string
        title = generate_chat_room_title(
            "Pythonの学習計画を作って",
            "3週間の計画を提案します。",
            "openai/gpt-oss-120b",
            llm_response_getter=lambda *_args, **_kwargs: '{"title": "Python学習計画"}',
        )

        self.assertEqual(title, "Python学習計画")

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

    # 日本語: ルームのリネームが成功した場合に、生成されたタイトルが返却されることを検証します。
    # English: Verify that the generated title is returned when the conditional room rename succeeds.
    def test_maybe_auto_title_returns_title_only_when_rename_succeeds(self):
        calls = []

        # 日本語: リネームの成功状況を記録するモック関数
        # English: Mock rename function that records calls and returns True (success)
        def conditional_rename(room_id, title, allowed_current_titles):
            calls.append((room_id, title, allowed_current_titles))
            return True

        # 日本語: タイトル生成LLM呼び出しをモックして期待されるタイトルを返す
        # English: Mock the title generation LLM call to return the expected title
        with patch("services.chat_title.generate_chat_room_title", return_value="相談の整理"):
            title = maybe_auto_title_chat_room(
                chat_room_id="room-1",
                user_message="相談したい",
                assistant_response="回答です",
                model="openai/gpt-oss-120b",
                allowed_current_titles=["新規チャット", "相談したい"],
                conditional_rename=conditional_rename,
            )

        # 日本語: 返却されたタイトルが正しく、リネームが正しい引数で呼ばれていることを確認
        # English: Confirm the returned title is correct and rename was called with expected arguments
        self.assertEqual(title, "相談の整理")
        self.assertEqual(calls, [("room-1", "相談の整理", ["新規チャット", "相談したい"])])


if __name__ == "__main__":
    unittest.main()
