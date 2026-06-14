import unittest
from unittest.mock import patch

from services.chat_title import (
    build_initial_title_candidates,
    generate_chat_room_title,
    maybe_auto_title_chat_room,
)


# 日本語: Chat Titleの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Chat Title.
class ChatTitleTestCase(unittest.TestCase):
    # 日本語: generateチャットroomタイトルparsesjsonレスポンスことを検証します。
    # English: Verify that generate chat room title parses json response.
    def test_generate_chat_room_title_parses_json_response(self):
        title = generate_chat_room_title(
            "Pythonの学習計画を作って",
            "3週間の計画を提案します。",
            "openai/gpt-oss-120b",
            llm_response_getter=lambda *_args, **_kwargs: '{"title": "Python学習計画"}',
        )

        self.assertEqual(title, "Python学習計画")

    # 日本語: ビルドinitialタイトルcandidates含むタスクsetupことを検証します。
    # English: Verify that build initial title candidates includes task setup.
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

    # 日本語: renamesucceedsのとき、maybeautoタイトル返却するタイトルonlyことを検証します。
    # English: Verify that maybe auto title returns title only when rename succeeds.
    def test_maybe_auto_title_returns_title_only_when_rename_succeeds(self):
        calls = []

        # 日本語: conditional rename に関する処理の入口です。
        # English: Entry point for logic related to conditional rename.
        def conditional_rename(room_id, title, allowed_current_titles):
            calls.append((room_id, title, allowed_current_titles))
            return True

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
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
