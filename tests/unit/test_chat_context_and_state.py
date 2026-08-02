import unittest

from services.chat_context import (
    GENERATIVE_UI_EXECUTION_CONTRACT,
    build_context_messages,
    build_room_summary,
    select_recent_messages,
    trim_text_to_token_budget,
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
        self.assertIn(
            "An answer that ends with explanation alone is incomplete",
            context_messages[5]["content"],
        )
        self.assertEqual(context_messages[-1]["content"], "third")

    def test_latest_user_request_survives_long_fetched_url_context(self):
        question = "この資料を読んで、最も重要な結論を3点で教えてください。"
        content = (
            "<fetched_urls>\n"
            '<url href="https://example.com/long">\n'
            f"{'A' * 2000}\n"
            "</url>\n"
            "</fetched_urls>\n\n"
            f"{question}"
        )

        selected = select_recent_messages(
            [{"role": "user", "content": content}],
            token_budget=40,
        )

        self.assertEqual(len(selected), 1)
        self.assertIn(question, selected[0]["content"])
        self.assertLessEqual(len(selected[0]["content"]), 40 * 4)

    def test_latest_user_request_survives_combined_url_and_attachment_context(self):
        question = "添付資料とURLの内容を比較して、日本語で差分を説明して。"
        content = (
            "<fetched_urls>\n"
            '<url href="https://example.com/a">\n'
            f"{'URL' * 500}\n"
            "</url>\n"
            "</fetched_urls>\n\n"
            "<attached_files>\n"
            "<attachment_safety_note>参照データ</attachment_safety_note>\n"
            '<file name="notes.txt">\n'
            f"{'資料' * 500}\n"
            "</file>\n"
            "</attached_files>\n\n"
            f"{question}"
        )

        selected = select_recent_messages(
            [{"role": "user", "content": content}],
            token_budget=48,
        )

        self.assertEqual(len(selected), 1)
        self.assertIn(question, selected[0]["content"])
        self.assertLessEqual(len(selected[0]["content"]), 48 * 4)

    def test_latest_normal_message_keeps_existing_trimming_behavior(self):
        content = "normal message " * 100
        token_budget = 20

        selected = select_recent_messages(
            [{"role": "user", "content": content}],
            token_budget=token_budget,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(
            selected[0]["content"],
            trim_text_to_token_budget(content, token_budget),
        )

    def test_short_reference_augmented_message_remains_unchanged(self):
        content = (
            "<attached_files>\n"
            '<file name="notes.txt">short reference</file>\n'
            "</attached_files>\n\n"
            "What is the conclusion?"
        )

        selected = select_recent_messages(
            [{"role": "user", "content": content}],
            token_budget=100,
        )

        self.assertEqual(selected, [{"role": "user", "content": content}])

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
