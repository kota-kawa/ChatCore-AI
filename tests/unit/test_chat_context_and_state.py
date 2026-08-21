import unittest

from services.chat_context import (
    CONTEXT_TOKEN_BUDGET,
    build_context_messages,
    build_room_summary,
    estimate_token_count,
    normalize_message_text,
    select_recent_messages,
    trim_text_to_token_budget,
)
from services.chat_prompt import (
    GENERATIVE_UI_EXECUTION_CONTRACT,
    build_base_system_prompt as _build_base_system_prompt,
)


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

    # 日本語: build_context_messages が、すべてのシステム文脈と最新メッセージを正しい順序で組み立てることを検証します。
    # English: Verify that build_context_messages assembles every system context and recent message in order.
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
            project_instructions="project",
        )

        # 日本語: 順序がベース→プロフィール→プロジェクト→タスク→要約→記憶→生成UI契約→最新であることを確認します。
        # English: Confirm base -> profile -> project -> task -> summary -> memory -> UI contract -> recent.
        self.assertEqual(context_messages[0]["content"], "base")
        self.assertEqual(context_messages[1]["content"], "profile")
        self.assertIn("project", context_messages[2]["content"])
        self.assertEqual(context_messages[3]["content"], "task")
        self.assertIn("summary text", context_messages[4]["content"])
        self.assertIn("Kota", context_messages[5]["content"])
        self.assertEqual(context_messages[6]["role"], "system")
        self.assertEqual(
            context_messages[6]["content"],
            GENERATIVE_UI_EXECUTION_CONTRACT,
        )
        self.assertIn(
            "An answer that ends with explanation alone is incomplete",
            context_messages[6]["content"],
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
        self.assertLessEqual(estimate_token_count(selected[0]["content"]), 40)

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
        self.assertLessEqual(estimate_token_count(selected[0]["content"]), 48)

    def test_latest_normal_message_preserves_trailing_constraints_when_trimmed(self):
        trailing_request = "最後に、結論は日本語の箇条書き3点だけで回答してください。"
        content = "資料の本文です。" * 100 + trailing_request
        # 予算は実トークン基準。末尾要求だけで約19トークンあるため、主題と
        # 末尾要求の両方を残すにはそれを上回る予算が要る。
        # Budgets are in real tokens. The trailing request alone costs about 19,
        # so keeping both the subject and the request needs more than that.
        token_budget = 56

        selected = select_recent_messages(
            [{"role": "user", "content": content}],
            token_budget=token_budget,
        )

        self.assertEqual(len(selected), 1)
        self.assertIn("資料の本文", selected[0]["content"])
        self.assertIn(trailing_request, selected[0]["content"])
        self.assertLessEqual(estimate_token_count(selected[0]["content"]), token_budget)

    def test_long_reference_request_preserves_trailing_constraints_when_request_is_oversized(self):
        trailing_request = "出力はJSONではなく日本語の文章だけにしてください。"
        content = (
            "<attached_files>\n<file name=\"notes.txt\">資料</file>\n</attached_files>\n\n"
            + "詳細な依頼です。" * 100
            + trailing_request
        )

        token_budget = 66

        selected = select_recent_messages(
            [{"role": "user", "content": content}],
            token_budget=token_budget,
        )

        self.assertEqual(len(selected), 1)
        self.assertIn(trailing_request, selected[0]["content"])
        self.assertLessEqual(estimate_token_count(selected[0]["content"]), token_budget)

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

    def test_recent_message_guarantee_respects_max_messages(self):
        selected = select_recent_messages(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
                {"role": "user", "content": "third"},
            ],
            token_budget=100,
            max_messages=1,
        )

        self.assertEqual(selected, [{"role": "user", "content": "third"}])

    def test_long_previous_answer_keeps_the_complete_recent_turn(self):
        previous_user = "私の名前はKotaで、日本語で回答してください。"
        previous_assistant = "確認しました。" + "詳細な説明です。" * 2500
        latest_user = "私の名前と希望する回答言語を教えてください。"

        context_messages = build_context_messages(
            base_system_prompt=_build_base_system_prompt(),
            user_profile_prompt=None,
            task_prompt=None,
            room_summary="",
            memory_facts=[],
            recent_messages=[
                {"role": "user", "content": previous_user},
                {"role": "assistant", "content": previous_assistant},
                {"role": "user", "content": latest_user},
            ],
        )

        history = [message for message in context_messages if message["role"] != "system"]
        self.assertEqual([message["role"] for message in history], ["user", "assistant", "user"])
        self.assertEqual(history[0]["content"], previous_user)
        self.assertEqual(history[-1]["content"], latest_user)
        self.assertLess(len(history[1]["content"]), len(previous_assistant))

    def test_optional_system_context_cannot_consume_recent_history_reservation(self):
        messages = [
            {"role": "user", "content": "最初の要件: 日本語で回答する"},
            {"role": "assistant", "content": "承知しました。" + "説明" * 1600},
            {"role": "user", "content": "前の要件を踏まえて続けてください。"},
        ]
        context_messages = build_context_messages(
            base_system_prompt=_build_base_system_prompt(),
            user_profile_prompt="profile " * 3000,
            task_prompt="task " * 3000,
            room_summary="summary " * 3000,
            memory_facts=["memory " * 1000],
            project_instructions="project " * 3000,
            recent_messages=messages,
        )

        total_tokens = sum(estimate_token_count(message["content"]) for message in context_messages)
        history = [message for message in context_messages if message["role"] != "system"]
        self.assertLessEqual(total_tokens, CONTEXT_TOKEN_BUDGET)
        self.assertEqual([message["role"] for message in history], ["user", "assistant", "user"])
        self.assertEqual(history[0]["content"], messages[0]["content"])

    def test_long_history_is_summarized_before_twelve_messages(self):
        messages = [
            {"role": "user", "content": "最初の要件: 日本語で回答"},
            {"role": "assistant", "content": "長い回答" * 4000},
            {"role": "user", "content": "続きの質問"},
        ]

        summary, archived_count = build_room_summary(messages)

        self.assertEqual(archived_count, 1)
        self.assertIn("最初の要件", summary)

    # 日本語: 日本語テキストが英語より多くのトークンとして見積もられることを検証します。
    # English: Verify that Japanese text is estimated to cost more tokens than Latin text.
    def test_estimate_token_count_is_script_aware(self):
        japanese = "あ" * 120
        latin = "a" * 120

        self.assertGreater(estimate_token_count(japanese), estimate_token_count(latin))
        # 4文字=1トークンの旧見積もり(30)より大幅に多く見積もられること
        # Must be far above the old 4-characters-per-token estimate of 30
        self.assertGreaterEqual(estimate_token_count(japanese), 70)
        self.assertEqual(estimate_token_count(latin), 30)

    # 日本語: 切り詰め結果が、日本語でも英語でも必ず予算内に収まることを検証します。
    # English: Verify that trimmed text always fits the budget for both Japanese and Latin input.
    def test_trim_text_to_token_budget_never_exceeds_budget(self):
        samples = [
            "これは日本語の長い文章です。" * 200,
            "This is a long English sentence. " * 200,
            ("混在テキスト mixed content " * 200),
        ]

        for sample in samples:
            for budget in (1, 5, 40, 300):
                with self.subTest(budget=budget, sample=sample[:12]):
                    trimmed = trim_text_to_token_budget(sample, budget)
                    self.assertLessEqual(estimate_token_count(trimmed), budget)

    # 日本語: 長文ユーザー発話の末尾要求を残す切り詰めも、予算を超えないことを検証します。
    # English: Verify the trailing-request-preserving trim also stays within budget.
    def test_recent_message_selection_stays_within_budget_for_japanese(self):
        messages = [
            {"role": "user", "content": "最初の依頼です。" * 300},
            {"role": "assistant", "content": "詳しい回答です。" * 300},
            {"role": "user", "content": "続きをお願いします。" * 300},
        ]

        selected = select_recent_messages(messages, token_budget=200)

        total = sum(estimate_token_count(message["content"]) for message in selected)
        self.assertLessEqual(total, 200)

    # 日本語: 貼り付けられたコードの字下げが、モデルへ渡る直前まで保持されることを検証します。
    # English: Verify that indentation in pasted code survives all the way to the model payload.
    def test_recent_messages_preserve_code_indentation(self):
        code_message = (
            "このコードを直して\n"
            "```python\n"
            "def outer():\n"
            "    if flag:\n"
            "        return inner(\n"
            "            value,\n"
            "        )\n"
            "    return None\n"
            "```"
        )

        selected = select_recent_messages(
            [{"role": "user", "content": code_message}],
            token_budget=400,
        )

        content = selected[0]["content"]
        self.assertIn("    if flag:", content)
        self.assertIn("        return inner(", content)
        self.assertIn("            value,", content)

    # 日本語: ネストした Markdown 箇条書きの階層が保持されることを検証します。
    # English: Verify that nested Markdown list levels are preserved.
    def test_recent_messages_preserve_nested_markdown_list_levels(self):
        list_message = "手順\n- 親項目\n  - 子項目\n    - 孫項目"

        selected = select_recent_messages(
            [{"role": "user", "content": list_message}],
            token_budget=400,
        )

        content = selected[0]["content"]
        self.assertIn("\n  - 子項目", content)
        self.assertIn("\n    - 孫項目", content)

    # 日本語: 行中の余分な空白と行末の空白は従来どおり圧縮されることを検証します。
    # English: Verify that redundant mid-line and trailing whitespace is still compacted.
    def test_normalize_message_text_strips_rendered_citation_chips(self):
        replayed_answer = (
            "高山のおすすめは古い町並です"
            '<a class="web-search-citation" href="https://example.com/a" '
            'target="_blank" title="観光8選">'
            '<span class="web-search-citation__label">観光8選</span></a>。'
        )
        truncated_answer = (
            "平湯大滝が魅力です"
            '<a class="web-search-citation" href="https://example.com/a" title="観光8選'
        )

        self.assertEqual(
            normalize_message_text(replayed_answer),
            "高山のおすすめは古い町並です。",
        )
        self.assertEqual(
            normalize_message_text(truncated_answer),
            "平湯大滝が魅力です",
        )

    def test_normalize_message_text_still_compacts_redundant_whitespace(self):
        self.assertEqual(
            normalize_message_text("語句    の   あいだ   \n次の行   "),
            "語句 の あいだ\n次の行",
        )


if __name__ == "__main__":
    unittest.main()
