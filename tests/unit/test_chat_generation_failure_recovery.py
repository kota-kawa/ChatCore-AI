"""失敗したターンでも、生成できた回答を捨てずに返しきることを検証する。

Verifies that a failed turn still delivers whatever answer it managed to generate.

回答ステップの本文は「ツール呼び出しが無い」と確定するまで配信されない。そのため
配信前に落ちると、モデルが書き終えた本文がバッファにしか残らない。ここではその本文が
保存・配信されること、調査ステップの障害が回答へ縮退すること、終端イベントが必ず
1つ出ることを確認する。
The body of an answer step is not published until the step is known to request no tools, so a
failure before that point leaves everything the model wrote in a buffer. These tests cover
that the buffered body is persisted and delivered, that a failed research step degrades into
an answer, and that exactly one terminal event always reaches the client.
"""

import json
import unittest
from unittest.mock import Mock, patch

from services.chat_agent_budget import AgentStepBudget
from services.chat_generation import ChatGenerationJob
from services.llm import (
    LlmAuthenticationError,
    LlmRateLimitError,
    LlmUpstreamServiceError,
)


def tool_call(name, **arguments):
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def event_names(job):
    return [event.event for event in job._events]


def terminal_event(job):
    return job._events[-1]


class ChatGenerationFailureRecoveryTestCase(unittest.TestCase):
    def make_job(self, **kwargs):
        saved = Mock(return_value=None)
        on_error = Mock()
        job = ChatGenerationJob(
            conversation_messages=[{"role": "user", "content": "説明して"}],
            model="openai/gpt-oss-120b",
            persist_response=saved,
            on_error=on_error,
            **kwargs,
        )
        return job, saved, on_error

    # 再試行の待機でテストを遅くしないため、既定では再試行を無効にして走らせる。
    # Run without retries by default so the backoff never slows the tests down.
    def run_job(self, job, stream, *, max_retries="0", web_search=False):
        with (
            patch.dict(
                "services.chat_generation.os.environ",
                {"LLM_STREAM_MAX_RETRIES": max_retries},
                clear=False,
            ),
            patch("services.chat_generation.is_web_search_enabled", return_value=web_search),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream),
            patch("services.chat_generation.choose_web_search_images", return_value=[]),
        ):
            job._run()

    # 日本語: 本文の配信前に落ちたターンが、書けていた回答を保存して締めることを検証します。
    # English: Verify a turn that failed before publishing still saves the body it wrote.
    def test_failure_mid_answer_saves_the_generated_body(self):
        def stream(_messages, _model, **_kwargs):
            yield "ここまでは書けています。"
            raise LlmUpstreamServiceError("Groq API reported a mid-stream failure.")

        job, saved, on_error = self.make_job()
        self.run_job(job, stream)

        self.assertTrue(job.is_done)
        self.assertEqual(terminal_event(job).event, "incomplete")
        self.assertIn("ここまでは書けています。", terminal_event(job).payload["response"])
        self.assertTrue(terminal_event(job).payload["partial"])
        # 本文が残った以上、ユーザー発話を巻き戻すエラーコールバックは呼ばれない。
        # A turn that kept its body never rolls the user's own message back.
        on_error.assert_not_called()
        saved.assert_called_once()
        self.assertIn("ここまでは書けています。", saved.call_args.args[0])
        self.assertEqual(job._telemetry.salvaged_partial_answers, 1)

    # 日本語: 本文を1文字も書けなかった失敗は、これまで通りエラーとして通知されることを検証します。
    # English: Verify a failure that produced no body at all is still reported as an error.
    def test_failure_without_any_body_still_reports_an_error(self):
        def stream(_messages, _model, **_kwargs):
            raise LlmUpstreamServiceError("Groq API reported a mid-stream failure.")
            yield  # pragma: no cover - keeps the callable a generator

        job, saved, on_error = self.make_job()
        self.run_job(job, stream)

        self.assertEqual(terminal_event(job).event, "error")
        on_error.assert_called_once()
        saved.assert_not_called()

    # 日本語: 調査ステップの障害でターンを落とさず、ツールなしの回答へ縮退することを検証します。
    # English: Verify a failed research step degrades to a tool-free answer instead of failing.
    def test_research_failure_degrades_to_a_tool_free_answer(self):
        offered_tools = []

        def stream(_messages, _model, *, tools=None, **_kwargs):
            offered_tools.append(bool(tools))
            if tools:
                raise LlmUpstreamServiceError("Groq API reported a mid-stream failure.")
            yield "手元の情報で回答します。"

        job, saved, on_error = self.make_job()
        self.run_job(job, stream, web_search=True)

        self.assertEqual(offered_tools, [True, False])
        self.assertEqual(terminal_event(job).event, "done")
        self.assertIn("手元の情報で回答します。", terminal_event(job).payload["response"])
        on_error.assert_not_called()
        saved.assert_called_once()
        self.assertEqual(job._telemetry.research_failure_recoveries, 1)

    # 日本語: 縮退しても回復しない設定不備は、そのままエラーになることを検証します。
    # English: Verify a configuration failure that degrading cannot fix still errors out.
    def test_authentication_failure_is_not_degraded(self):
        calls = 0

        def stream(_messages, _model, **_kwargs):
            nonlocal calls
            calls += 1
            raise LlmAuthenticationError("Groq API authentication failed.")
            yield  # pragma: no cover - keeps the callable a generator

        job, _saved, _on_error = self.make_job()
        self.run_job(job, stream, web_search=True)

        self.assertEqual(calls, 1)
        self.assertEqual(terminal_event(job).event, "error")

    # 日本語: レート制限が、待機のうえで再試行されることを検証します。
    # English: Verify a rate limit is retried after waiting instead of failing immediately.
    def test_rate_limit_is_retried(self):
        attempts = 0

        def stream(_messages, _model, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise LlmRateLimitError("Groq API rate limit exceeded.", retry_after_seconds=1)
            yield "混雑のあと回答できました。"

        job, saved, _on_error = self.make_job()
        with patch("services.chat_generation.ChatGenerationJob._sleep_with_cancel", return_value=False):
            self.run_job(job, stream, max_retries="2")

        self.assertEqual(attempts, 2)
        self.assertEqual(terminal_event(job).event, "done")
        saved.assert_called_once()

    # 日本語: 待ちきれない Retry-After を指示されたら、その場で再試行しないことを検証します。
    # English: Verify an unaffordable Retry-After skips the in-place retry.
    def test_rate_limit_with_a_long_retry_after_is_not_retried(self):
        attempts = 0

        def stream(_messages, _model, **_kwargs):
            nonlocal attempts
            attempts += 1
            raise LlmRateLimitError("Groq API rate limit exceeded.", retry_after_seconds=120)
            yield  # pragma: no cover - keeps the callable a generator

        job, _saved, _on_error = self.make_job()
        self.run_job(job, stream, max_retries="2")

        self.assertEqual(attempts, 1)
        self.assertEqual(terminal_event(job).event, "error")

    # 日本語: 仕上げ処理が落ちても終端イベントが必ず出ることを検証します。
    # English: Verify a crash during finalization still publishes a terminal event.
    def test_finalization_crash_still_publishes_a_terminal_event(self):
        def stream(_messages, _model, **_kwargs):
            yield "回答本文です。"

        job, _saved, _on_error = self.make_job()
        with patch.object(
            ChatGenerationJob,
            "_finalize_generation",
            side_effect=RuntimeError("finalize exploded"),
        ):
            self.run_job(job, stream)

        self.assertTrue(job.is_done)
        self.assertEqual(terminal_event(job).event, "error")
        self.assertIn("error", event_names(job))

    # 日本語: モデル判断の上限が、回復用の再試行を含めても超えないことを検証します。
    # English: Verify the model-decision budget holds even across recovery replays.
    def test_model_decision_budget_reserves_the_last_turn_for_the_answer(self):
        offered_tools = []

        def stream(_messages, _model, *, tools=None, **_kwargs):
            offered_tools.append(bool(tools))
            if tools:
                yield json.dumps([tool_call("web_search", query=f"q{len(offered_tools)}")])
                return
            yield "上限内で回答します。"

        job, saved, _on_error = self.make_job()
        budget = AgentStepBudget(3, 6)
        with (
            patch("services.chat_generation.AgentStepBudget.from_environment", return_value=budget),
            patch("services.chat_generation.search_brave_llm_context", return_value=None),
        ):
            self.run_job(job, stream, web_search=True)

        # 3回のうち2回が調査、最後の1回が回答。上限を超える呼び出しは起きない。
        # Two of the three decisions research and the last one answers; nothing runs past it.
        self.assertEqual(offered_tools, [True, True, False])
        self.assertEqual(budget.llm_turns, 3)
        saved.assert_called_once()


if __name__ == "__main__":
    unittest.main()
