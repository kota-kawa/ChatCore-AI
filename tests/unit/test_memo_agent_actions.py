import json
import unittest
from unittest.mock import patch

from services.memo_agent_actions import (
    MEMO_EDIT_MAX_CONTENT_LENGTH,
    MEMO_EDIT_MAX_TITLE_LENGTH,
    build_memo_edit_messages,
    classify_memo_intent,
    parse_memo_edit_response,
)


# 日本語: メモエージェントの意図分類（編集/QA）をテストするクラス。
# English: Test class for memo agent intent classification (edit vs QA).
class ClassifyMemoIntentTestCase(unittest.TestCase):
    # 日本語: 明確な編集指示はLLMを呼び出さずに"edit"へ分類されることを検証します。
    # English: Verify that clear edit phrases are classified as "edit" without calling the LLM.
    def test_edit_hints_classified_deterministically(self):
        with patch("services.memo_agent_actions.get_llm_response") as mock_llm:
            for message in (
                "誤字脱字を修正して",
                "この文章を英語に翻訳して",
                "冒頭に挨拶を追記して",
                "本文を読みやすく整理して書き直して",
            ):
                self.assertEqual(classify_memo_intent(message), "edit", message)
        mock_llm.assert_not_called()

    # 日本語: 明確な質問・要約はLLMを呼び出さずに"qa"へ分類されることを検証します。
    # English: Verify that clear read-only phrases are classified as "qa" without calling the LLM.
    def test_qa_hints_classified_deterministically(self):
        with patch("services.memo_agent_actions.get_llm_response") as mock_llm:
            for message in (
                "このメモを要約して",
                "このメモの結論を教えて",
                "この用語とは何？",
            ):
                self.assertEqual(classify_memo_intent(message), "qa", message)
        mock_llm.assert_not_called()

    # 日本語: 曖昧なメッセージはLLM分類の結果を採用することを検証します。
    # English: Verify that ambiguous messages use the LLM classification result.
    def test_ambiguous_message_uses_llm_classification(self):
        with patch(
            "services.memo_agent_actions.get_llm_response",
            return_value='{"intent": "edit"}',
        ) as mock_llm:
            self.assertEqual(classify_memo_intent("箇条書きが読みにくいと思う"), "edit")
        mock_llm.assert_called_once()

    # 日本語: LLM失敗時は安全側の"qa"にフォールバックすることを検証します。
    # English: Verify the safe "qa" fallback when the LLM call fails.
    def test_llm_failure_falls_back_to_qa(self):
        with patch(
            "services.memo_agent_actions.get_llm_response",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(classify_memo_intent("うーん、これどう思う"), "qa")


# 日本語: メモ編集計画のパース・検証ロジックをテストするクラス。
# English: Test class for parsing and validating memo edit plans.
class ParseMemoEditResponseTestCase(unittest.TestCase):
    # 日本語: 正常なJSON応答から編集計画が生成されることを検証します。
    # English: Verify that a valid JSON response produces an edit plan.
    def test_parses_valid_edit_plan(self):
        response = json.dumps({
            "description": "誤字を修正します",
            "steps": [
                {
                    "action": "memo_edit",
                    "description": "誤字を直した本文へ置き換えます",
                    "title": "会議メモ（修正版）",
                    "content": "修正後の本文です。",
                }
            ],
        }, ensure_ascii=False)

        plan = parse_memo_edit_response(response)

        self.assertIsNotNone(plan)
        self.assertEqual(plan["description"], "誤字を修正します")
        self.assertEqual(len(plan["steps"]), 1)
        step = plan["steps"][0]
        self.assertEqual(step["action"], "memo_edit")
        self.assertEqual(step["content"], "修正後の本文です。")
        self.assertEqual(step["title"], "会議メモ（修正版）")
        self.assertEqual(step["risk"], "low")

    # 日本語: マークダウンのコードフェンスに包まれたJSONもパースできることを検証します。
    # English: Verify that JSON wrapped in a markdown code fence is parsed.
    def test_parses_plan_inside_code_fence(self):
        response = (
            "```json\n"
            '{"description": "整形します", "steps": [{"action": "memo_edit", '
            '"description": "本文を整形", "content": "整形済み本文"}]}\n'
            "```"
        )

        plan = parse_memo_edit_response(response)

        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"][0]["content"], "整形済み本文")
        self.assertNotIn("title", plan["steps"][0])

    # 日本語: 複数ステップが返された場合でも有効な1件だけ採用されることを検証します。
    # English: Verify that only the first valid step is kept when multiple steps are returned.
    def test_keeps_only_first_valid_step(self):
        response = json.dumps({
            "description": "編集します",
            "steps": [
                {"action": "click", "description": "不正なステップ", "selector": "#x"},
                {"action": "memo_edit", "description": "有効な編集", "content": "本文A"},
                {"action": "memo_edit", "description": "余分な編集", "content": "本文B"},
            ],
        }, ensure_ascii=False)

        plan = parse_memo_edit_response(response)

        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(plan["steps"][0]["content"], "本文A")

    # 日本語: 本文が空・欠落・長すぎる編集計画は破棄されることを検証します。
    # English: Verify that plans with empty, missing, or overlong content are rejected.
    def test_rejects_invalid_content(self):
        empty = json.dumps({
            "steps": [{"action": "memo_edit", "description": "空", "content": "   "}],
        })
        missing = json.dumps({
            "steps": [{"action": "memo_edit", "description": "欠落"}],
        })
        overlong = json.dumps({
            "steps": [
                {
                    "action": "memo_edit",
                    "description": "長すぎ",
                    "content": "a" * (MEMO_EDIT_MAX_CONTENT_LENGTH + 1),
                }
            ],
        })

        self.assertIsNone(parse_memo_edit_response(empty))
        self.assertIsNone(parse_memo_edit_response(missing))
        self.assertIsNone(parse_memo_edit_response(overlong))

    # 日本語: 不正なJSONや空のsteps、非JSONテキストはNoneになることを検証します。
    # English: Verify that invalid JSON, empty steps, and plain text return None.
    def test_rejects_non_plans(self):
        self.assertIsNone(parse_memo_edit_response(""))
        self.assertIsNone(parse_memo_edit_response("編集できませんでした。"))
        self.assertIsNone(parse_memo_edit_response('{"steps": []}'))
        self.assertIsNone(parse_memo_edit_response('{"steps": "broken"}'))
        self.assertIsNone(parse_memo_edit_response('{"steps": [{"action":'))

    # 日本語: タイトルがDB上限を超える場合に切り詰められることを検証します。
    # English: Verify that overlong titles are clamped to the DB limit.
    def test_clamps_overlong_title(self):
        response = json.dumps({
            "steps": [
                {
                    "action": "memo_edit",
                    "description": "改題",
                    "title": "t" * (MEMO_EDIT_MAX_TITLE_LENGTH + 40),
                    "content": "本文",
                }
            ],
        })

        plan = parse_memo_edit_response(response)

        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["steps"][0]["title"]), MEMO_EDIT_MAX_TITLE_LENGTH)


# 日本語: 編集計画生成用のLLMメッセージ構築をテストするクラス。
# English: Test class for building the LLM messages used for edit plan generation.
class BuildMemoEditMessagesTestCase(unittest.TestCase):
    # 日本語: システムプロンプトにメモ本文が参照情報として区切られて含まれることを検証します。
    # English: Verify the system prompt embeds the memo context inside untrusted-data markers.
    def test_system_message_wraps_memo_context_as_untrusted(self):
        messages = build_memo_edit_messages(
            "【現在開いているメモ】\n本文:\nテスト本文",
            [{"role": "user", "content": "誤字を直して"}],
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("memo_edit", messages[0]["content"])
        self.assertIn("参照情報ここから", messages[0]["content"])
        self.assertIn("テスト本文", messages[0]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "誤字を直して"})


if __name__ == "__main__":
    unittest.main()
