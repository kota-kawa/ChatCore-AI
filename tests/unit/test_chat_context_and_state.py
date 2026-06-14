import unittest

from services.chat_context import build_context_messages, build_room_summary
from services.chat_state import extract_memory_facts


# 日本語: ChatContextAndStateTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatContextAndStateTestCase.
class ChatContextAndStateTestCase(unittest.TestCase):
    # 日本語: test build room summary summarizes archived messages のテスト検証を担当します。
    # English: Handle verifying test behavior for test build room summary summarizes archived messages.
    def test_build_room_summary_summarizes_archived_messages(self):
        messages = []
        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
        for index in range(16):
            role = "user" if index % 2 == 0 else "assistant"
            messages.append({"role": role, "content": f"message-{index}"})

        summary, archived_count = build_room_summary(messages)

        self.assertEqual(archived_count, 4)
        self.assertIn("<conversation_summary>", summary)
        self.assertIn("message-0", summary)

    # 日本語: test build context messages includes summary memory and recent messages のテスト検証を担当します。
    # English: Handle verifying test behavior for test build context messages includes summary memory and recent messages.
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

        self.assertEqual(context_messages[0]["content"], "base")
        self.assertEqual(context_messages[1]["content"], "profile")
        self.assertEqual(context_messages[2]["content"], "task")
        self.assertIn("summary text", context_messages[3]["content"])
        self.assertIn("Kota", context_messages[4]["content"])
        self.assertEqual(context_messages[-1]["content"], "third")

    # 日本語: test extract memory facts handles explicit and structured preferences のテスト検証を担当します。
    # English: Handle verifying test behavior for test extract memory facts handles explicit and structured preferences.
    def test_extract_memory_facts_handles_explicit_and_structured_preferences(self):
        facts = extract_memory_facts(
            "覚えて: 箇条書きで短く答えて\nMy name is Kota.\nI prefer concise answers."
        )

        self.assertIn("箇条書きで短く答えて", facts)
        self.assertIn("ユーザー名: Kota", facts)
        self.assertIn("ユーザーの好み: concise answers", facts)


if __name__ == "__main__":
    unittest.main()
