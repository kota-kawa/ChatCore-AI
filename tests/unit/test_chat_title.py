import unittest
from unittest.mock import patch

from services.chat_title import (
    build_initial_title_candidates,
    generate_chat_room_title,
    maybe_auto_title_chat_room,
)


class ChatTitleTestCase(unittest.TestCase):
    def test_generate_chat_room_title_parses_json_response(self):
        title = generate_chat_room_title(
            "Pythonの学習計画を作って",
            "3週間の計画を提案します。",
            "openai/gpt-oss-120b",
            llm_response_getter=lambda *_args, **_kwargs: '{"title": "Python学習計画"}',
        )

        self.assertEqual(title, "Python学習計画")

    def test_build_initial_title_candidates_includes_task_setup(self):
        candidates = build_initial_title_candidates(
            "【タスク】メール返信\n【状況・作業環境】採用面接の日程調整",
            task_launch_request={
                "task": "メール返信",
                "setup_info": "採用面接の日程調整",
            },
        )

        self.assertIn("新規チャット", candidates)
        self.assertIn("採用面接の日程調整", candidates)
        self.assertIn("メール返信", candidates)

    def test_maybe_auto_title_returns_title_only_when_rename_succeeds(self):
        calls = []

        def conditional_rename(room_id, title, allowed_current_titles):
            calls.append((room_id, title, allowed_current_titles))
            return True

        with patch("services.chat_title.generate_chat_room_title", return_value="相談の整理"):
            title = maybe_auto_title_chat_room(
                chat_room_id="room-1",
                user_message="相談したい",
                assistant_response="回答です",
                model="openai/gpt-oss-120b",
                allowed_current_titles=["新規チャット", "相談したい"],
                conditional_rename=conditional_rename,
            )

        self.assertEqual(title, "相談の整理")
        self.assertEqual(calls, [("room-1", "相談の整理", ["新規チャット", "相談したい"])])


if __name__ == "__main__":
    unittest.main()
