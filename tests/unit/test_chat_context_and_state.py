import unittest

from services.chat_context import (
    GENERATIVE_UI_EXECUTION_CONTRACT,
    build_context_messages,
    build_room_summary,
)
from services.chat_state import extract_memory_facts


# 日本語: チャットのコンテキスト構築と状態管理ロジックをテストするクラス。
# English: Test class for chat context construction and state management logic.
class ChatContextAndStateTestCase(unittest.TestCase):
    # 日本語: build_room_summary が古いメッセージを要約し、アーカイブ数を返すことを検証します。
    # English: Verify that build_room_summary summarizes older messages and returns the archived count.
    def test_build_room_summary_summarizes_archived_messages(self):
        # 日本語: user/assistant が交互に並ぶ16件のダミーメッセージを作成
        # English: Create 16 dummy messages alternating between user and assistant
        messages = []
        for index in range(16):
            role = "user" if index % 2 == 0 else "assistant"
            messages.append({"role": role, "content": f"message-{index}"})

        summary, archived_count = build_room_summary(messages)

        # 日本語: 最初の4件がアーカイブされ、要約テキストに含まれることを確認
        # English: Confirm that the first 4 messages are archived and appear in the summary text
        self.assertEqual(archived_count, 4)
        self.assertIn("<conversation_summary>", summary)
        self.assertIn("message-0", summary)

    # 日本語: build_context_messages が、システムプロンプト・要約・記憶・最新メッセージを正しい順序で組み立てることを検証します。
    # English: Verify that build_context_messages correctly assembles system prompts, summary, memory, and recent messages in order.
    def test_build_context_messages_includes_summary_memory_and_recent_messages(self):
        context_messages = build_context_messages(
            base_system_prompt="base",
            user_profile_prompt="profile",
            task_prompt="task",
            room_summary="summary text",
            memory_facts=["ユーザー名: Kota", "回答スタイルの希望: 箇条書き"],
            recent_messages=[
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
                {"role": "user", "content": "third"},
            ],
        )

        # 日本語: メッセージリストの順序が正しいことを確認（ベース→プロフィール→タスク→要約→記憶→生成UI最終契約→最新）
        # English: Confirm the message order is correct (base -> profile -> task -> summary -> memory -> final UI contract -> recent)
        self.assertEqual(context_messages[0]["content"], "base")
        self.assertEqual(context_messages[1]["content"], "profile")
        self.assertEqual(context_messages[2]["content"], "task")
        self.assertIn("summary text", context_messages[3]["content"])
        self.assertIn("Kota", context_messages[4]["content"])
        self.assertEqual(context_messages[5]["role"], "system")
        self.assertEqual(
            context_messages[5]["content"],
            GENERATIVE_UI_EXECUTION_CONTRACT,
        )
        self.assertIn("説明文だけで終える回答は未完了", context_messages[5]["content"])
        self.assertEqual(context_messages[-1]["content"], "third")

    # 日本語: extract_memory_facts が「覚えて:」の指示や英語の自己紹介から記憶すべき事実を抽出することを検証します。
    # English: Verify that extract_memory_facts correctly extracts facts from explicit "覚えて:" instructions and English self-introductions.
    def test_extract_memory_facts_handles_explicit_and_structured_preferences(self):
        facts = extract_memory_facts(
            "覚えて: 箇条書きで短く答えて\nMy name is Kota.\nI prefer concise answers."
        )

        # 日本語: 各ソースから適切に事実が抽出されていることを確認
        # English: Confirm facts are correctly extracted from each source
        self.assertIn("箇条書きで短く答えて", facts)
        self.assertIn("ユーザー名: Kota", facts)
        self.assertIn("ユーザーの好み: concise answers", facts)


if __name__ == "__main__":
    unittest.main()
