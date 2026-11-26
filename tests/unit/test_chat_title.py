"""チャットルームのタイトル生成（services.chat_title）と初期タイトル候補の組み立てを検証するテスト。

Tests chat room title generation and initial title candidates in services.chat_title.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from blueprints.chat.room_title import chat_room_title
from services.chat_title import (
    build_initial_title_candidates,
    generate_chat_room_title,
)
from services.llm import LIGHTWEIGHT_TASK_MODEL
from services.repositories.chat_room_access import get_owned_room_title, rename_room_if_current_title_in
from tests.helpers.request_helpers import build_request


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


class ChatRoomTitleLookupTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_title_lookup_requires_room_id_and_never_queries_for_guests(self):
        with patch("blueprints.chat.room_title.get_owned_chat_room_title", new_callable=AsyncMock) as load_title:
            self.assertEqual((await chat_room_title(build_request())).status_code, 400)
            guest = build_request(query_string=b"room_id=room-1")
            self.assertEqual((await chat_room_title(guest)).status_code, 404)
            load_title.assert_not_awaited()

    async def test_title_lookup_calls_owned_read_and_disables_caching(self):
        request = build_request(query_string=b"room_id=room-1", session={"user_id": 42})
        with patch("blueprints.chat.room_title.get_owned_chat_room_title", new_callable=AsyncMock) as load_title:
            load_title.side_effect = [None, "会話タイトル"]
            self.assertEqual((await chat_room_title(request)).status_code, 404)
            response = await chat_room_title(request)
        self.assertEqual(load_title.await_args.args, ("room-1", 42))
        self.assertEqual(json.loads(response.body), {"title": "会話タイトル"})
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_deferred_rename_checks_owner_existing_title_and_saved_answer(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
        renamed = await rename_room_if_current_title_in(
            session, "room-1", "新しい名前", ["仮の名前"], user_id=42, assistant_message_id=8,
        )
        self.assertFalse(renamed)
        statement = session.execute.await_args.args[0].compile()
        sql = str(statement)
        self.assertIn("chat_rooms.user_id =", sql)
        self.assertIn("chat_rooms.title IN", sql)
        self.assertIn("EXISTS", sql)
        self.assertIn("chat_history.id =", sql)
        self.assertIn("chat_history.chat_room_id =", sql)
        self.assertIn(8, statement.params.values())

    async def test_title_query_matches_owner_and_normal_room(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value="会話タイトル")
        self.assertEqual(await get_owned_room_title(session, "room-1", 42), "会話タイトル")
        statement = session.scalar.await_args.args[0].compile()
        self.assertIn("chat_rooms.user_id =", str(statement))
        self.assertIn("chat_rooms.mode =", str(statement))
        self.assertCountEqual(statement.params.values(), ["room-1", 42, "normal"])


if __name__ == "__main__":
    unittest.main()
