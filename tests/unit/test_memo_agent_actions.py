import json
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

from services.memo_agent_actions import (
    MEMO_EDIT_MAX_CONTENT_LENGTH,
    MEMO_EDIT_MAX_TITLE_LENGTH,
    MemoAgentContext,
    apply_memo_edits,
    build_memo_edit_messages,
    classify_memo_intent,
    generate_memo_edit_plan,
    parse_memo_edit_response,
)

# 日本語: フロントエンドの applyMemoEdits と共有するケース表。
# English: Case table shared with applyMemoEdits on the frontend.
EDIT_CASES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "memo_agent_edit_cases.json"

# 日本語: ケース表の失敗種別と、それを示す問題文の目印。問題文は作り直し時にLLMへそのまま渡る。
# English: Failure kinds in the case table and the marker each one leaves in the problem text sent to the LLM.
FAILURE_MARKERS = {
    "no_edits": "at least one edit",
    "too_many_edits": "are allowed",
    "empty_old_string": "old_string is empty",
    "not_found": "was not found",
    "ambiguous": "places in the body",
    "overlap": "overlapping parts",
    "too_long": "The edited body would be",
}


# 日本語: ケース表の {"repeat": s, "times": n} を実際の文字列へ展開します。
# English: Expand {"repeat": s, "times": n} in the case table into the actual string.
def _expand(value: Any) -> Any:
    if isinstance(value, dict) and "repeat" in value:
        return value["repeat"] * value["times"]
    return value


def _load_edit_cases() -> list[dict[str, Any]]:
    cases = json.loads(EDIT_CASES_PATH.read_text(encoding="utf-8"))["cases"]
    return [
        {
            "name": case["name"],
            "body": _expand(case["body"]),
            "edits": [
                {"old_string": _expand(edit["old_string"]), "new_string": _expand(edit["new_string"])}
                for edit in case["edits"]
            ],
            "expected": {key: _expand(value) for key, value in case["expected"].items()},
        }
        for case in cases
    ]


def _plan_response(step: dict[str, Any], description: str = "編集します") -> str:
    return json.dumps({"description": description, "steps": [step]}, ensure_ascii=False)


# 日本語: メモエージェントの意図分類（編集/QA）をテストするクラス。
# English: Test class for memo agent intent classification (edit vs QA).
class ClassifyMemoIntentTestCase(unittest.TestCase):
    # 日本語: 明確な編集指示でも固定語句判定を使わずLLMへ委譲することを検証します。
    # English: Verify that even obvious edit requests are delegated to the LLM instead of phrase matching.
    def test_edit_requests_always_use_llm_classification(self):
        with patch("services.memo_agent_actions.get_llm_response") as mock_llm:
            mock_llm.return_value = '{"intent": "edit"}'
            for message in (
                "誤字脱字を修正して",
                "この文章を英語に翻訳して",
                "冒頭に挨拶を追記して",
                "本文を読みやすく整理して書き直して",
            ):
                self.assertEqual(classify_memo_intent(message), "edit", message)
        self.assertEqual(mock_llm.call_count, 4)

    # 日本語: 明確な質問・要約でも固定語句判定を使わずLLMへ委譲することを検証します。
    # English: Verify that even obvious read-only requests are delegated to the LLM instead of phrase matching.
    def test_qa_requests_always_use_llm_classification(self):
        with patch("services.memo_agent_actions.get_llm_response") as mock_llm:
            mock_llm.return_value = '{"intent": "qa"}'
            for message in (
                "このメモを要約して",
                "このメモの結論を教えて",
                "この用語とは何？",
            ):
                self.assertEqual(classify_memo_intent(message), "qa", message)
        self.assertEqual(mock_llm.call_count, 3)

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


# 日本語: 部分置換の適用規則を、フロントエンドと共有するケース表で検証するクラス。
# English: Verify the partial-edit rules against the case table shared with the frontend.
class ApplyMemoEditsTestCase(unittest.TestCase):
    # 日本語: ケース表の全件で、適用後の本文または失敗種別が期待どおりになることを検証します。
    # English: Verify every case in the table yields the expected body or failure kind.
    def test_shared_case_table(self):
        cases = _load_edit_cases()
        self.assertGreater(len(cases), 0)
        for case in cases:
            with self.subTest(case["name"]):
                result = apply_memo_edits(case["body"], case["edits"])
                expected = case["expected"]
                if "body" in expected:
                    self.assertEqual(result.problems, ())
                    self.assertEqual(result.body, expected["body"])
                else:
                    self.assertIsNone(result.body)
                    marker = FAILURE_MARKERS[expected["failure"]]
                    self.assertTrue(
                        any(marker in problem for problem in result.problems),
                        f"{marker!r} not in {result.problems!r}",
                    )

    # 日本語: 作り直し用の理由に、どの編集が何箇所に一致したかが入ることを検証します。
    # English: Verify the retry reasons name the edit and how many places it matched.
    def test_problems_name_the_edit_and_match_count(self):
        result = apply_memo_edits(
            "りんご と りんご と りんご",
            [{"old_string": "と", "new_string": "&"}, {"old_string": "みかん", "new_string": "x"}],
        )

        self.assertIsNone(result.body)
        self.assertIn("edits[0].old_string matches 2 places in the body", result.problems[0])
        self.assertIn("edits[1].old_string was not found in the body", result.problems[1])
        self.assertIn("punctuation, spaces, and line breaks", result.problems[1])


# 日本語: メモ編集計画のパース・検証ロジックをテストするクラス。
# English: Test class for parsing and validating memo edit plans.
class ParseMemoEditResponseTestCase(unittest.TestCase):
    STORED_BODY = "会議は月曜日です。\n議題は予算です。"

    def _parse(self, text: str, *, stored_body: str | None = None, body_truncated: bool = False):
        return parse_memo_edit_response(
            text,
            stored_body=self.STORED_BODY if stored_body is None else stored_body,
            body_truncated=body_truncated,
        )

    # 日本語: 正常な全文置換のJSON応答から編集計画が生成されることを検証します。
    # English: Verify that a valid full-replacement JSON response produces an edit plan.
    def test_parses_valid_full_replacement_plan(self):
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

        result = self._parse(response)

        self.assertEqual(result.problems, ())
        plan = result.plan
        self.assertIsNotNone(plan)
        self.assertEqual(plan["description"], "誤字を修正します")
        self.assertEqual(len(plan["steps"]), 1)
        step = plan["steps"][0]
        self.assertEqual(step["action"], "memo_edit")
        self.assertEqual(step["content"], "修正後の本文です。")
        self.assertNotIn("edits", step)
        self.assertEqual(step["title"], "会議メモ（修正版）")
        self.assertEqual(step["risk"], "low")

    # 日本語: 部分置換の計画は保存済み本文で照合され、改行をLFへそろえた edits として返ることを検証します。
    # English: Verify a partial-edit plan is matched against the stored body and returned with LF-normalized edits.
    def test_parses_valid_partial_edit_plan(self):
        response = _plan_response({
            "action": "memo_edit",
            "description": "曜日を直します",
            "edits": [
                {"old_string": "月曜日です。\r\n議題", "new_string": "火曜日です。\r\n議題"},
            ],
        })

        result = self._parse(response, stored_body="会議は月曜日です。\r\n議題は予算です。")

        self.assertEqual(result.problems, ())
        step = result.plan["steps"][0]
        self.assertEqual(step["edits"], [{"old_string": "月曜日です。\n議題", "new_string": "火曜日です。\n議題"}])
        self.assertNotIn("content", step)
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

        plan = self._parse(response).plan

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
                {"action": "memo_edit", "description": "照合できない編集", "edits": [
                    {"old_string": "存在しない文", "new_string": "x"},
                ]},
                {"action": "memo_edit", "description": "有効な編集", "content": "本文A"},
                {"action": "memo_edit", "description": "余分な編集", "content": "本文B"},
            ],
        }, ensure_ascii=False)

        result = self._parse(response)

        self.assertIsNotNone(result.plan)
        self.assertEqual(len(result.plan["steps"]), 1)
        self.assertEqual(result.plan["steps"][0]["content"], "本文A")

    # 日本語: 1つのステップに edits と content の両方、またはどちらも無い場合は、理由付きで破棄されることを検証します。
    # English: Verify a step with both or neither of edits and content is rejected with a reason.
    def test_requires_exactly_one_of_edits_and_content(self):
        both = _plan_response({
            "action": "memo_edit",
            "description": "両方",
            "content": "本文",
            "edits": [{"old_string": "月曜日", "new_string": "火曜日"}],
        })
        neither = _plan_response({"action": "memo_edit", "description": "どちらも無し", "title": "新題"})

        both_result = self._parse(both)
        neither_result = self._parse(neither)

        self.assertIsNone(both_result.plan)
        self.assertIn("not both", both_result.problems[0])
        self.assertIsNone(neither_result.plan)
        self.assertIn("either edits or content", neither_result.problems[0])

    # 日本語: 本文が空・長すぎる全文置換は理由付きで破棄されることを検証します。
    # English: Verify full replacements with empty or overlong content are rejected with a reason.
    def test_rejects_invalid_content(self):
        empty = _plan_response({"action": "memo_edit", "description": "空", "content": "   "})
        overlong = _plan_response({
            "action": "memo_edit",
            "description": "長すぎ",
            "content": "a" * (MEMO_EDIT_MAX_CONTENT_LENGTH + 1),
        })

        empty_result = self._parse(empty)
        overlong_result = self._parse(overlong)

        self.assertIsNone(empty_result.plan)
        self.assertIn("content is empty", empty_result.problems[0])
        self.assertIsNone(overlong_result.plan)
        self.assertIn(f"at most {MEMO_EDIT_MAX_CONTENT_LENGTH} characters", overlong_result.problems[0])

    # 日本語: 形の崩れた edits や、本文を空にする部分置換は理由付きで破棄されることを検証します。
    # English: Verify malformed edits and partial edits that empty the body are rejected with a reason.
    def test_rejects_malformed_or_emptying_edits(self):
        malformed = _plan_response({
            "action": "memo_edit",
            "description": "形が不正",
            "edits": [{"old_string": "月曜日"}],
        })
        not_a_list = _plan_response({"action": "memo_edit", "description": "配列でない", "edits": "月曜日"})
        emptying = _plan_response({
            "action": "memo_edit",
            "description": "全部消す",
            "edits": [{"old_string": self.STORED_BODY, "new_string": " "}],
        })

        self.assertIn("edits[0] must be an object", self._parse(malformed).problems[0])
        self.assertIn("non-empty array", self._parse(not_a_list).problems[0])
        emptying_result = self._parse(emptying)
        self.assertIsNone(emptying_result.plan)
        self.assertIn("leave the body empty", emptying_result.problems[0])

    # 日本語: 切り詰めたメモでは、見えている範囲への部分置換は全文で照合して通り、全文置換は拒否されることを検証します。
    # English: Verify a truncated memo accepts partial edits (matched against the full body) and refuses full replacement.
    def test_truncated_body_allows_edits_only(self):
        stored_body = "冒頭の段落。\n" + ("中略。" * 10) + "\n末尾の段落。"
        edits = _plan_response({
            "action": "memo_edit",
            "description": "冒頭を直す",
            "edits": [{"old_string": "冒頭の段落。", "new_string": "最初の段落。"}],
        })
        full = _plan_response({"action": "memo_edit", "description": "全文", "content": "短い本文"})

        edits_result = self._parse(edits, stored_body=stored_body, body_truncated=True)
        full_result = self._parse(full, stored_body=stored_body, body_truncated=True)

        self.assertIsNotNone(edits_result.plan)
        self.assertEqual(edits_result.plan["steps"][0]["edits"][0]["new_string"], "最初の段落。")
        self.assertIsNone(full_result.plan)
        self.assertIn("The body is truncated", full_result.problems[0])
        self.assertIn("Use edits instead", full_result.problems[0])

    # 日本語: 不正なJSONや空のsteps、非JSONテキストは、作り直しの理由を持たない空の結果になることを検証します。
    # English: Verify invalid JSON, empty steps, and plain text yield an empty result without retry reasons.
    def test_rejects_non_plans_without_problems(self):
        for text in (
            "",
            "編集できませんでした。",
            '{"steps": []}',
            '{"steps": "broken"}',
            '{"steps": [{"action":',
            '{"steps": [{"action": "click", "description": "x", "selector": "#x"}]}',
        ):
            with self.subTest(text):
                result = self._parse(text)
                self.assertIsNone(result.plan)
                self.assertEqual(result.problems, ())

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

        plan = self._parse(response).plan

        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["steps"][0]["title"]), MEMO_EDIT_MAX_TITLE_LENGTH)


# 日本語: 編集計画の生成と、検証に通らない計画の1回だけの作り直しをテストするクラス。
# English: Test class for generating edit plans and regenerating a rejected plan exactly once.
class GenerateMemoEditPlanTestCase(unittest.TestCase):
    CONTEXT = MemoAgentContext(
        prompt_context="[Memo currently open]\nBody:\n会議は月曜日です。",
        stored_body="会議は月曜日です。",
        body_truncated=False,
    )
    HISTORY: ClassVar[list[dict[str, str]]] = [{"role": "user", "content": "月曜日を火曜日に直して"}]
    BAD = _plan_response({
        "action": "memo_edit",
        "description": "曜日を直す",
        "edits": [{"old_string": "月よう日", "new_string": "火曜日"}],
    })
    GOOD = _plan_response({
        "action": "memo_edit",
        "description": "曜日を直す",
        "edits": [{"old_string": "月曜日", "new_string": "火曜日"}],
    })

    def _generate(self, context: MemoAgentContext | None = None):
        return generate_memo_edit_plan(
            context or self.CONTEXT,
            self.HISTORY,
            locale="ja",
            model="test-model",
        )

    # 日本語: 1回目で有効な計画が得られればLLM呼び出しは1回だけであることを検証します。
    # English: Verify a valid first plan needs a single LLM call.
    def test_returns_first_valid_plan(self):
        with patch("services.memo_agent_actions.get_llm_response", return_value=self.GOOD) as mock_llm:
            plan = self._generate()

        self.assertEqual(plan["steps"][0]["edits"], [{"old_string": "月曜日", "new_string": "火曜日"}])
        mock_llm.assert_called_once()
        self.assertEqual(mock_llm.call_args.args[1], "test-model")

    # 日本語: 照合できない計画は、理由と直前の応答を添えて1回だけ作り直させることを検証します。
    # English: Verify an unmatched plan is regenerated once, with the previous reply and the reasons.
    def test_regenerates_once_with_reasons(self):
        with patch("services.memo_agent_actions.get_llm_response", side_effect=[self.BAD, self.GOOD]) as mock_llm:
            plan = self._generate()

        self.assertIsNotNone(plan)
        self.assertEqual(mock_llm.call_count, 2)
        first_messages = mock_llm.call_args_list[0].args[0]
        retry_messages = mock_llm.call_args_list[1].args[0]
        self.assertEqual(retry_messages[: len(first_messages)], first_messages)
        self.assertEqual(retry_messages[-2], {"role": "assistant", "content": self.BAD})
        self.assertEqual(retry_messages[-1]["role"], "user")
        self.assertIn("not a new request from the user", retry_messages[-1]["content"])
        self.assertIn("- edits[0].old_string was not found in the body", retry_messages[-1]["content"])

    # 日本語: 作り直しても無効なら None を返し、それ以上は呼ばないことを検証します。
    # English: Verify None is returned, with no further calls, when the regenerated plan is still invalid.
    def test_gives_up_after_one_regeneration(self):
        with patch("services.memo_agent_actions.get_llm_response", side_effect=[self.BAD, self.BAD]) as mock_llm:
            plan = self._generate()

        self.assertIsNone(plan)
        self.assertEqual(mock_llm.call_count, 2)

    # 日本語: 計画を作らない応答（steps が空）は作り直さないことを検証します。
    # English: Verify a reply that declines to plan (empty steps) is not regenerated.
    def test_does_not_regenerate_when_no_plan_was_attempted(self):
        with patch("services.memo_agent_actions.get_llm_response", return_value='{"steps": []}') as mock_llm:
            plan = self._generate()

        self.assertIsNone(plan)
        mock_llm.assert_called_once()

    # 日本語: 切り詰めたメモでは、プロンプトに部分置換だけを使う規則が入ることを検証します。
    # English: Verify the prompt carries the edits-only rules for a truncated memo.
    def test_truncated_memo_prompt_requires_edits(self):
        context = MemoAgentContext(
            prompt_context=self.CONTEXT.prompt_context,
            stored_body=self.CONTEXT.stored_body,
            body_truncated=True,
        )
        with patch("services.memo_agent_actions.get_llm_response", return_value=self.GOOD) as mock_llm:
            plan = self._generate(context)

        self.assertIsNotNone(plan)
        system_content = mock_llm.call_args.args[0][0]["content"]
        self.assertIn("<long_memo>", system_content)
        self.assertIn('Use "edits" only', system_content)
        self.assertIn("You can edit only the part of the body that is shown", system_content)


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
        self.assertIn("START OF REFERENCE MATERIAL", messages[0]["content"])
        self.assertIn("テスト本文", messages[0]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "誤字を直して"})

    # 日本語: メモ編集計画にも混在言語入力の共通判定順序が渡されることを検証します。
    # English: Verify the shared mixed-language decision order is included for memo edit plans.
    def test_system_message_includes_shared_response_language_policy(self):
        messages = build_memo_edit_messages(
            "[Memo currently open]\nBody:\nExample",
            [{"role": "user", "content": "英語ログを見て、要約は日本語で追記して"}],
            locale="en",
        )

        system_content = messages[0]["content"]
        self.assertIn("the part that states the user's request or instruction", system_content)
        self.assertIn("larger share", system_content)
        self.assertIn("saved interface language (English)", system_content)
        self.assertIn("the top-level description, the step description, a new title", system_content)
        self.assertIn("newly written memo content", system_content)
        self.assertIn("Keep existing memo text in its original language", system_content)

    # 日本語: 部分置換と全文置換の使い分けと、部分置換の書き方がプロンプトに含まれることを検証します。
    # English: Verify the prompt explains when to use partial vs. full replacement and how to write edits.
    def test_system_message_explains_partial_and_full_replacement(self):
        system_content = build_memo_edit_messages("本文", [{"role": "user", "content": "誤字を直して"}])[0]["content"]

        self.assertIn('"edits" (partial replacement)', system_content)
        self.assertIn('"content" (full replacement)', system_content)
        self.assertIn('"old_string"', system_content)
        self.assertIn("either \"edits\" or \"content\", never both", system_content)
        self.assertIn("appear exactly once in the body", system_content)
        self.assertIn("Use at most 20 edits", system_content)
        self.assertNotIn("<long_memo>", system_content)


if __name__ == "__main__":
    unittest.main()
