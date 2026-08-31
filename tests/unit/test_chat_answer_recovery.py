# 長いステップのターンで最終回答が「途中で切れる」「本文が二重化する」「無音になる」
# のを防ぐ回復経路と、その入力・ステップ予算を検証する。
# Covers the recovery path that keeps a long, many-step turn from truncating, duplicating, or
# going silent, together with the input and step budgets that bound it.

import json
import unittest
from unittest.mock import patch

from services.chat_agent_budget import AgentStepBudget, get_max_llm_turns, get_max_tool_calls
from services.chat_answer_continuation import (
    FINAL_ANSWER_CONTINUATION_OVERLAP_CHARS,
    FinalAnswerContinuationStalledError,
    get_final_answer_max_continuations,
    looks_like_restarted_answer,
    splice_restarted_answer,
    stream_final_answer_with_recovery,
    strip_continuation_overlap,
)
from services.chat_input_budget import (
    compact_tool_messages,
    estimate_messages_tokens,
)
from services.llm import (
    LlmInputLimitError,
    LlmOutputLimitError,
)


def _run_recovery(
    passes,
    *,
    adopt_buffer=None,
    adopt_buffer_mode=None,
    should_stop=None,
):
    """Drive the recovery helper over scripted passes and capture what it published."""
    published: list[str] = []
    events: list[tuple[str, dict]] = []
    calls: list[str] = []

    def iter_stream(_messages, phase):
        calls.append(phase)
        return iter(passes[len(calls) - 1]())

    result = stream_final_answer_with_recovery(
        [{"role": "user", "content": "question"}],
        model="openai/gpt-oss-120b",
        iter_stream=iter_stream,
        publish_chunk=published.append,
        publish_event=lambda name, payload: events.append((name, payload)),
        should_stop=should_stop or (lambda: False),
        adopt_buffer=adopt_buffer,
        adopt_buffer_mode=adopt_buffer_mode,
    )
    return result, "".join(published), published, events


class ContinuationOverlapTestCase(unittest.TestCase):
    def test_exact_boundary_overlap_is_removed(self):
        self.assertEqual(strip_continuation_overlap("abcdef", "defghi"), "ghi")

    def test_unrelated_continuation_is_kept_whole(self):
        self.assertEqual(strip_continuation_overlap("abcdef", "xyz"), "xyz")

    # 日本語: 継続が最初から書き直された場合の検出を検証します。末尾一致だけを見る
    # 従来の判定では検出できず、本文が丸ごと二重化していました。
    # English: Detect a continuation that restarted from the beginning. Checking only the
    # suffix/prefix boundary missed this case and duplicated the whole answer.
    def test_restarted_answer_is_detected_only_on_a_long_prefix_match(self):
        existing = "あ" * 400
        self.assertTrue(looks_like_restarted_answer(existing, existing + "続き"))
        self.assertFalse(looks_like_restarted_answer(existing, "まったく違う続き"))
        # 見出しの再掲程度の短い一致は書き直しと見なさない。
        # A short repeated heading is not a rewrite.
        self.assertFalse(looks_like_restarted_answer("短い見出し", "短い見出しの続き"))

    def test_restarted_answer_is_spliced_after_the_existing_tail(self):
        existing = "".join(f"文{index}。" for index in range(200))
        rewrite = existing + "追加された結論。"

        self.assertEqual(splice_restarted_answer(existing, rewrite), "追加された結論。")

    def test_unsplicable_rewrite_reports_none_instead_of_duplicating(self):
        existing = "".join(f"文{index}。" for index in range(200))

        self.assertIsNone(splice_restarted_answer(existing, "まったく別の本文です。"))


class FinalAnswerRecoveryTestCase(unittest.TestCase):
    def test_first_pass_streams_live_without_buffering(self):
        result, text, published, _ = _run_recovery([lambda: ["a", "b", "c"]])

        self.assertIsNone(result.error)
        self.assertEqual(text, "abc")
        self.assertEqual(published, ["a", "b", "c"])
        self.assertEqual(result.continuation_count, 0)

    # 日本語: 継続パスは境界の重複を消せる分だけ貯めたら、以降はそのまま配信する。
    # 全文をバッファしていた頃は、継続中にUIが数十秒〜数分まったく無音になっていた。
    # English: A continuation buffers only enough to remove the boundary overlap and streams
    # the rest live. Buffering the whole pass left the UI silent for the entire continuation.
    def test_continuation_streams_live_after_the_dedupe_window(self):
        tail = "X" * (FINAL_ANSWER_CONTINUATION_OVERLAP_CHARS * 3)

        def first_pass():
            yield "head"
            raise LlmOutputLimitError("limit", reason="max_output_tokens")

        def continuation_pass():
            for index in range(0, len(tail), 100):
                yield tail[index: index + 100]

        result, text, published, events = _run_recovery([first_pass, continuation_pass])

        self.assertIsNone(result.error)
        self.assertEqual(text, "head" + tail)
        self.assertEqual(result.continuation_count, 1)
        # 先頭の重複除去ぶんを1回まとめて出したあと、残りは細切れで流れる。
        # One flush covers the dedupe window, then the remainder arrives incrementally.
        self.assertGreater(len(published), 10)
        # 未配信のまま残る量は重複除去の窓ぶんだけに収まる。
        # Only the dedupe window is ever held back from the viewer.
        self.assertLessEqual(
            len(published[1]),
            FINAL_ANSWER_CONTINUATION_OVERLAP_CHARS + 100,
        )
        self.assertEqual(events[0][0], "response_generation_started")
        self.assertEqual(events[0][1]["phase"], "continuation")

    def test_continuation_removes_an_exact_boundary_overlap(self):
        def first_pass():
            yield "first half"
            raise LlmOutputLimitError("limit", reason="max_output_tokens")

        result, text, _, _ = _run_recovery(
            [first_pass, lambda: ["first half and second half"]]
        )

        self.assertIsNone(result.error)
        self.assertEqual(text, "first half and second half")

    # 日本語: 継続が最初から書き直しても本文が二重化しないことを検証します。
    # English: A continuation that rewrites from the start must not duplicate the answer.
    def test_restarted_continuation_is_spliced_instead_of_duplicated(self):
        body = "".join(f"段落{index}の本文です。" for index in range(60))

        def first_pass():
            yield body
            raise LlmOutputLimitError("limit", reason="max_output_tokens")

        def restarted_pass():
            yield body
            yield "そして結論です。"

        result, text, _, _ = _run_recovery([first_pass, restarted_pass])

        self.assertIsNone(result.error)
        self.assertEqual(text, body + "そして結論です。")
        self.assertTrue(result.restart_trimmed)

    # 日本語: 進捗ゼロの継続を繰り返しても費用と待ち時間が増えるだけなので打ち切ります。
    # English: A continuation that adds nothing only costs money and latency, so stop.
    def test_continuation_stops_when_a_pass_adds_nothing(self):
        def first_pass():
            yield "same text"
            raise LlmOutputLimitError("limit", reason="max_output_tokens")

        def empty_pass():
            yield "same text"
            raise LlmOutputLimitError("limit", reason="max_output_tokens")

        result, text, _, _ = _run_recovery([first_pass, empty_pass])

        self.assertIsInstance(result.error, LlmOutputLimitError)
        self.assertEqual(text, "same text")
        self.assertTrue(result.stalled)
        self.assertEqual(result.continuation_count, 1)

    # 日本語: 出力上限ではなく正常終了した継続が境界重複だけを返しても、成功扱いにせず
    # 部分回答としてUIへ渡します。これがないと「続き」ボタンを表示できません。
    # English: A normally finished continuation that returns only the repeated boundary is still
    # a partial answer, not success, so the UI can offer the continuation action.
    def test_normally_finished_continuation_without_progress_is_stalled(self):
        def first_pass():
            yield "same text"
            raise LlmOutputLimitError("limit", reason="max_output_tokens")

        result, text, _, _ = _run_recovery([first_pass, lambda: ["same text"]])

        self.assertIsInstance(result.error, FinalAnswerContinuationStalledError)
        self.assertTrue(result.stalled)
        self.assertEqual(result.continuation_count, 1)
        self.assertEqual(text, "same text")
        self.assertIn("continuation_stalled", result.reasons)

    def test_rewrite_buffer_mode_is_reported_to_the_owner(self):
        body = "".join(f"段落{index}の本文です。" for index in range(60))
        modes: list[bool] = []

        def first_pass():
            yield body
            raise LlmOutputLimitError("limit", reason="max_output_tokens")

        result, text, _, _ = _run_recovery(
            [first_pass, lambda: [body, "結論"]],
            adopt_buffer_mode=modes.append,
        )

        self.assertIsNone(result.error)
        self.assertEqual(text, body + "結論")
        self.assertIn(False, modes)
        self.assertIn(True, modes)

    # 日本語: 入力超過を継続へ回すと入力がさらに増えて必ず再失敗するため、継続しません。
    # English: Continuing an input overflow grows the request and always fails again.
    def test_input_limit_never_triggers_a_continuation(self):
        def first_pass():
            yield "partial"
            raise LlmInputLimitError("too long")

        result, text, _, events = _run_recovery([first_pass])

        self.assertIsInstance(result.error, LlmInputLimitError)
        self.assertEqual(text, "partial")
        self.assertEqual(result.continuation_count, 0)
        self.assertEqual(events, [])

    def test_input_limit_without_any_output_is_raised_to_the_caller(self):
        def first_pass():
            yield from ()  # pragma: no cover - generator marker
            raise LlmInputLimitError("too long")

        with self.assertRaises(LlmInputLimitError):
            _run_recovery([first_pass])

    # 日本語: 未配信の継続バッファをジョブ側へ預け、停止・切断で失われないことを検証します。
    # English: The undelivered continuation buffer is handed to the job so a stop cannot lose it.
    def test_continuation_buffer_is_exposed_for_persistence(self):
        adopted: list[list[str]] = []

        def first_pass():
            yield "head"
            raise LlmOutputLimitError("limit", reason="max_output_tokens")

        def continuation_pass():
            yield "buffered tail"
            raise LlmOutputLimitError("limit", reason="max_output_tokens")

        with patch.dict("os.environ", {"LLM_FINAL_ANSWER_MAX_CONTINUATIONS": "1"}):
            result, text, _, _ = _run_recovery(
                [first_pass, continuation_pass],
                adopt_buffer=adopted.append,
            )

        self.assertEqual(len(adopted), 1)
        # 配信済みになった時点でバッファは空にし、二重保存を防ぐ。
        # The buffer is emptied once published so the text is never persisted twice.
        self.assertEqual(adopted[0], [])
        self.assertEqual(text, "headbuffered tail")
        self.assertIsInstance(result.error, LlmOutputLimitError)

    def test_default_continuation_budget_allows_three_passes(self):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("LLM_FINAL_ANSWER_MAX_CONTINUATIONS", None)
            self.assertEqual(get_final_answer_max_continuations(), 3)


class InputBudgetTestCase(unittest.TestCase):
    def _tool_message(self, index):
        return {
            "role": "tool",
            "tool_call_id": f"call-{index}",
            "name": "web_search",
            "content": json.dumps(
                {
                    "status": "completed",
                    "source_count": 2,
                    "sources": [
                        {
                            "evidence_id": f"src_{index}{position}",
                            "url": "https://example.com",
                            "title": "title",
                            "snippets": ["snippet " * 50],
                            "page_text": "page " * 500,
                        }
                        for position in range(2)
                    ],
                },
                ensure_ascii=False,
            ),
        }

    def test_messages_within_budget_are_returned_untouched(self):
        messages = [{"role": "user", "content": "short"}]

        compacted, count = compact_tool_messages(messages, max_tokens=10_000)

        self.assertIs(compacted, messages)
        self.assertEqual(count, 0)

    # 日本語: 予算超過時は古い根拠から本文→スニペットの順に削り、証拠IDは必ず残します。
    # 証拠IDが消えると引用マーカーの解決が壊れ、出典チップが出せなくなります。
    # English: Over budget, the oldest evidence loses page text then snippets, but the evidence
    # IDs always survive: losing them would break citation resolution and the source chips.
    def test_oldest_evidence_is_compacted_first_and_ids_survive(self):
        messages = [
            {"role": "user", "content": "question"},
            *(self._tool_message(index) for index in range(4)),
        ]
        original_tokens = estimate_messages_tokens(messages)

        compacted, count = compact_tool_messages(
            messages,
            max_tokens=original_tokens // 3,
        )

        self.assertGreater(count, 0)
        self.assertLess(estimate_messages_tokens(compacted), original_tokens)
        for index, message in enumerate(compacted):
            if message.get("role") != "tool":
                continue
            payload = json.loads(message["content"])
            self.assertTrue(
                all(source.get("evidence_id") for source in payload["sources"])
            )
        # 直近の根拠ほど回答に効くので、先に削られるのは古い方であること。
        # Later evidence matters more to the answer, so the oldest is compacted first.
        first_payload = json.loads(compacted[1]["content"])
        last_payload = json.loads(compacted[-1]["content"])
        self.assertLessEqual(
            len(json.dumps(first_payload, ensure_ascii=False)),
            len(json.dumps(last_payload, ensure_ascii=False)),
        )

    def test_minimum_budget_reduces_every_tool_result_to_its_evidence_ids(self):
        messages = [
            {"role": "user", "content": "question"},
            *(self._tool_message(index) for index in range(3)),
        ]

        compacted, count = compact_tool_messages(messages, max_tokens=1)

        self.assertEqual(count, 3)
        for message in compacted[1:]:
            payload = json.loads(message["content"])
            for source in payload["sources"]:
                self.assertEqual(list(source), ["evidence_id"])

    def test_non_json_tool_content_is_left_alone(self):
        messages = [
            {"role": "user", "content": "x" * 40_000},
            {"role": "tool", "tool_call_id": "call-1", "content": "plain text"},
        ]

        compacted, count = compact_tool_messages(messages, max_tokens=1)

        self.assertEqual(count, 0)
        self.assertEqual(compacted[1]["content"], "plain text")


class AgentStepBudgetTestCase(unittest.TestCase):
    # 日本語: 推論ターンとツール実行を別々に数えることで、検索を増やしても推論回数が
    # 削られないことを検証します。共有カウンタが「調査が深いほど回答が痩せる」原因でした.
    # English: Counting reasoning turns separately from tool calls keeps extra searches from
    # eating the reasoning budget, which is what made deeper research produce thinner answers.
    def test_tool_calls_do_not_consume_reasoning_turns(self):
        budget = AgentStepBudget(max_llm_turns=6, max_tool_calls=6)

        for _ in range(6):
            budget.start_tool_call()

        self.assertTrue(budget.tool_calls_exhausted)
        self.assertFalse(budget.llm_turns_exhausted)
        self.assertTrue(budget.research_exhausted)
        self.assertEqual(budget.llm_turns, 0)
        self.assertEqual(budget.step, 6)
        self.assertEqual(budget.max_steps, 12)

    def test_research_is_exhausted_when_either_budget_runs_out(self):
        budget = AgentStepBudget(max_llm_turns=2, max_tool_calls=6)

        budget.start_llm_turn()
        self.assertFalse(budget.research_exhausted)
        budget.start_llm_turn()
        self.assertTrue(budget.research_exhausted)

    # 日本語: 旧来の CHAT_AGENT_MAX_STEPS を残している環境でも意図どおり配分されることを検証します。
    # English: A deployment still setting the superseded CHAT_AGENT_MAX_STEPS keeps its intent.
    def test_legacy_total_step_budget_is_split_between_both_counters(self):
        with patch.dict(
            "os.environ",
            {"CHAT_AGENT_MAX_STEPS": "10"},
            clear=False,
        ):
            import os

            os.environ.pop("CHAT_AGENT_MAX_LLM_TURNS", None)
            os.environ.pop("CHAT_AGENT_MAX_TOOL_CALLS", None)
            self.assertEqual(get_max_tool_calls(), 5)
            self.assertEqual(get_max_llm_turns(), 5)

    def test_explicit_budgets_override_the_legacy_total(self):
        with patch.dict(
            "os.environ",
            {
                "CHAT_AGENT_MAX_STEPS": "10",
                "CHAT_AGENT_MAX_LLM_TURNS": "4",
                "CHAT_AGENT_MAX_TOOL_CALLS": "8",
            },
            clear=False,
        ):
            self.assertEqual(get_max_llm_turns(), 4)
            self.assertEqual(get_max_tool_calls(), 8)


if __name__ == "__main__":
    unittest.main()
