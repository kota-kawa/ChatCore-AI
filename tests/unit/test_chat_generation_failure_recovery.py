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
from services.chat_workspace_tools import build_workspace_toolbox
from services.generative_ui import NormalizedGenerativeResponse
from services.llm import (
    LlmAuthenticationError,
    LlmOutputLimitError,
    LlmRateLimitError,
    LlmToolSchemaError,
    LlmUpstreamServiceError,
)
from services.mcp_memo_service import McpMemoDetail, McpMemoListResult, McpMemoSummary

# タグを付けずに本文として届いた TurnState の封筒。
# A TurnState envelope that arrived as the body without its tags.
UNTAGGED_ENVELOPE = json.dumps(
    {
        "objective": "説明する",
        "unresolved_questions": [],
        "facts": [],
        "evidence_ids": [],
        "ready_to_answer": True,
    },
    ensure_ascii=False,
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
        conversation_messages = kwargs.pop("conversation_messages", [{"role": "user", "content": "説明して"}])
        job = ChatGenerationJob(
            conversation_messages=conversation_messages,
            model="openai/gpt-oss-120b",
            persist_response=saved,
            on_error=on_error,
            **kwargs,
        )
        return job, saved, on_error

    def make_memo_job(self, user_request):
        toolbox = build_workspace_toolbox(
            user_id=1,
            chat_room_id="room-1",
            memo_tools_enabled=True,
            external_input_in_turn=False,
        )
        return self.make_job(
            conversation_messages=[{"role": "user", "content": user_request}],
            workspace_tools=toolbox,
        )

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

    def test_unconfirmed_memo_change_claims_are_replaced_before_stream_and_save(self):
        cases = (
            (
                "旅行メモに追記してください",
                "旅行メモに次の項目を追記しました：\n- 10月12日 10:30 京都駅で友人と合流",
                "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。",
            ),
            (
                "旅行メモに追記してください",
                "追記が完了しました。以下の内容が旅行メモに追加されました：",
                "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。",
            ),
            (
                "出張メモの誤字を修正してください",
                "出張メモの『recieve』を『receive』に修正しました。",
                "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。",
            ),
            (
                "出張メモにある “recieve” の誤字を “receive” に直してください。",
                "出張メモの本文中にある **“recieve”** を **“receive”** に置き換えました。これで誤字が修正されています。",
                "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。",
            ),
            (
                "Create a memo called Weekend routine",
                "</think>\nI've proposed creating a memo called Weekend routine.",
                "The memo change was not submitted, and no approval card was created. Please try again.",
            ),
            (
                "Create a memo called Weekend routine",
                "The memo is waiting for your approval.",
                "The memo change was not submitted, and no approval card was created. Please try again.",
            ),
            (
                "新しいメモを作ってください",
                "新しいメモの作成提案を作成しました。",
                "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。",
            ),
            (
                "新しいメモを作ってください",
                "新しいメモに内容を追加する提案を作成しています。クリックで承認すると保存されます。",
                "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。",
            ),
            (
                "出張メモの誤字を修正してください",
                "この変更は承認待ちです。",
                "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。",
            ),
            (
                "Create a memo called Weekend routine",
                "- I've created a draft memo called Weekend routine.",
                "The memo change was not submitted, and no approval card was created. Please try again.",
            ),
            (
                "Update the travel memo.",
                "Your memo update is pending approval.",
                "The memo change was not submitted, and no approval card was created. Please try again.",
            ),
            (
                "Update the travel memo.",
                "Done — your memo is updated.",
                "The memo change was not submitted, and no approval card was created. Please try again.",
            ),
        )
        for request, model_reply, expected in cases:
            with self.subTest(model_reply=model_reply):
                job, saved, _on_error = self.make_memo_job(request)
                midpoint = len(model_reply) // 2
                self.run_job(job, lambda *_args, reply=model_reply, split=midpoint, **_kwargs: iter((reply[:split], reply[split:])))

                streamed = "".join(
                    event.payload["text"] for event in job._events if event.event == "chunk"
                )
                self.assertEqual(streamed, expected)
                self.assertEqual(terminal_event(job).payload["response"], expected)
                self.assertEqual(saved.call_args.args[0], expected)

    def test_memo_claim_guard_leaves_negations_examples_and_hypotheticals_alone(self):
        replies = (
            "旅行メモには追記していません。",
            "追記は完了していません。",
            "新しいメモの提案を作成していません。",
            "もし旅行メモに追記しました。その場合はカードが表示されます。",
            "もし新しいメモの提案を作成しています。その場合はカードを確認します。",
            "旅行メモに追記しましたという表示は、承認後に出ます。",
            "追記が完了しましたという表示は、承認後に出ます。",
            "新しいメモの提案を作成していますという表示は、承認前に出ます。",
            "例：旅行メモに追記しました。",
            "A memo will be waiting for your approval after it is proposed.",
            "\"I've proposed creating a memo\" is an example of a status message.",
            "操作手順を説明します。\nメモを作成しました。と表示されたら、カードを確認します。",
        )
        for reply in replies:
            with self.subTest(reply=reply):
                job, saved, _on_error = self.make_memo_job("メモの操作について説明して")
                self.run_job(job, lambda *_args, answer=reply, **_kwargs: iter((answer,)))

                self.assertEqual(terminal_event(job).payload["response"], reply)
                self.assertEqual(saved.call_args.args[0], reply)

    def test_memo_claim_guard_checks_later_lines(self):
        job, saved, _on_error = self.make_memo_job("旅行メモに追記してください")
        self.run_job(job, lambda *_args, **_kwargs: iter(("承知しました。\n旅行メモに追記しました。",)))

        expected = "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。"
        self.assertEqual(terminal_event(job).payload["response"], expected)
        self.assertEqual(saved.call_args.args[0], expected)

    def test_memo_claim_guard_checks_approval_card_status(self):
        reply = "旅行メモに次の項目を追記しました：予定を追加します。"
        for status, decision in (("pending", None), ("succeeded", "auto"), ("failed", "auto")):
            with self.subTest(status=status):
                job, saved, _on_error = self.make_memo_job("旅行メモに追記してください")
                job._tool_approval_parts.append(
                    {
                        "id": "card-1", "tool": "memo_append", "status": status, "decision": decision,
                        "preview": {"kind": "memo_append", "memo_id": 1, "memo_title": "旅行メモ"},
                    }
                )

                self.run_job(job, lambda *_args, **_kwargs: iter((reply,)))

                expected = (
                    reply if status == "succeeded"
                    else "この説明と承認カードの状態が一致しません。承認カードを確認してください。"
                )
                self.assertEqual(terminal_event(job).payload["response"], expected)
                self.assertEqual(saved.call_args.args[0], expected)

        job, saved, _on_error = self.make_memo_job("旅行メモに追記してください")
        job._tool_approval_parts.append(
            {
                "id": "card-2", "tool": "memo_append", "status": "pending", "decision": None,
                "preview": {"kind": "memo_append", "memo_id": 1, "memo_title": "旅行メモ"},
            }
        )
        proposal_reply = "旅行メモへの追記を提案しました。"
        self.run_job(job, lambda *_args, **_kwargs: iter((proposal_reply,)))
        self.assertEqual(terminal_event(job).payload["response"], proposal_reply)
        self.assertEqual(saved.call_args.args[0], proposal_reply)

    def test_memo_claim_guard_rejects_passive_completion_without_matching_card(self):
        cases = (
            (
                "旅行メモを更新してください",
                "旅行メモが更新されました。",
                "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。",
            ),
            (
                "Update the travel memo",
                "The memo has been updated.",
                "The memo change was not submitted, and no approval card was created. Please try again.",
            ),
        )
        for request, reply, expected in cases:
            with self.subTest(reply=reply):
                job, saved, _on_error = self.make_memo_job(request)
                self.run_job(job, lambda *_args, answer=reply, **_kwargs: iter((answer,)))
                self.assertEqual(terminal_event(job).payload["response"], expected)
                self.assertEqual(saved.call_args.args[0], expected)

    def test_memo_claim_guard_does_not_use_another_cards_success(self):
        other_memo = {
            "id": "card-other", "tool": "memo_append", "status": "succeeded", "decision": "auto",
            "preview": {"kind": "memo_append", "memo_id": 2, "memo_title": "仕事メモ"},
        }
        requested_memo = {
            "id": "card-requested", "tool": "memo_append", "status": "pending", "decision": None,
            "preview": {"kind": "memo_append", "memo_id": 1, "memo_title": "旅行メモ"},
        }
        wrong_action = {
            "id": "card-edit", "tool": "memo_edit", "status": "succeeded", "decision": "auto",
            "preview": {"kind": "memo_edit", "memo_id": 1, "memo_title": "旅行メモ"},
        }
        for cards in ((other_memo,), (other_memo, requested_memo), (wrong_action,)):
            with self.subTest(cards=cards):
                job, saved, _on_error = self.make_memo_job("旅行メモに追記してください")
                job._tool_approval_parts.extend(cards)
                self.run_job(job, lambda *_args, **_kwargs: iter(("旅行メモに追記しました。",)))
                expected = "この説明と承認カードの状態が一致しません。承認カードを確認してください。"
                self.assertEqual(terminal_event(job).payload["response"], expected)
                self.assertEqual(saved.call_args.args[0], expected)

    def test_memo_claim_guard_checks_a_claim_split_across_continuation(self):
        def stream(_messages, _model, *, generation_phase, **_kwargs):
            if generation_phase == "agent":
                yield "承知しました。旅行メモに"
                raise LlmOutputLimitError("limit", reason="max_output_tokens")
            yield "追記しました。"

        job, saved, _on_error = self.make_memo_job("旅行メモに追記してください")
        self.run_job(job, stream)

        streamed = "".join(event.payload["text"] for event in job._events if event.event == "chunk")
        self.assertNotIn("追記しました", streamed)
        expected = "承知しました。メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。"
        self.assertEqual(streamed, expected)
        self.assertEqual(
            terminal_event(job).payload["response"],
            expected,
        )
        self.assertEqual(saved.call_args.args[0], terminal_event(job).payload["response"])

    def test_memo_claim_guard_checks_final_normalization(self):
        job, saved, _on_error = self.make_memo_job("旅行メモに追記してください")
        repaired = NormalizedGenerativeResponse(
            text="旅行メモに追記しました。",
            parts=[{"type": "text", "text": "旅行メモに追記しました。"}],
            validation_errors=[],
        )
        with patch("services.chat_generation.normalize_response_with_artifact_retry", return_value=repaired):
            self.run_job(job, lambda *_args, **_kwargs: iter(("承知しました。",)))

        expected = "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。"
        self.assertEqual(terminal_event(job).payload["response"], expected)
        self.assertEqual(saved.call_args.args[0], expected)

    def test_cancel_replaces_an_unconfirmed_memo_claim_before_stream_and_save(self):
        job, saved, _on_error = self.make_memo_job("旅行メモに追記してください")
        job._pending_stream_chunks = ["旅行メモに次の項目を追記しました："]

        job.cancel()

        expected = "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。"
        self.assertEqual(terminal_event(job).payload["response"], expected)
        self.assertEqual(saved.call_args.args[0], expected)
        self.assertEqual(
            "".join(event.payload["text"] for event in job._events if event.event == "chunk"),
            expected,
        )

    def test_failed_stream_replaces_an_unconfirmed_memo_claim_before_salvage(self):
        def stream(_messages, _model, **_kwargs):
            yield "旅行メモに次の項目を追記しました："
            raise LlmUpstreamServiceError("The provider disconnected.")

        job, saved, _on_error = self.make_memo_job("旅行メモに追記してください")
        self.run_job(job, stream)

        expected = "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。"
        self.assertEqual(terminal_event(job).event, "incomplete")
        self.assertEqual(terminal_event(job).payload["response"], expected)
        self.assertEqual(saved.call_args.args[0], expected)
        self.assertEqual(
            "".join(event.payload["text"] for event in job._events if event.event == "chunk"),
            expected,
        )

    def test_memo_claim_guard_does_not_change_a_turn_without_memo_tools(self):
        reply = "旅行メモに次の項目を追記しました："
        job, saved, _on_error = self.make_job()

        self.run_job(job, lambda *_args, **_kwargs: iter((reply,)))

        self.assertEqual(terminal_event(job).payload["response"], reply)
        self.assertEqual(saved.call_args.args[0], reply)

    def test_memo_only_turn_withholds_external_lookup_tools_but_explicit_search_keeps_them(self):
        cases = (
            ("私のメモを日本語で要約してください。", False),
            ("最新のメモを要約してください。", False),
            ("私のメモを要約し、最新の外部情報をWeb検索して出典を付けてください。", True),
        )
        for request, expect_external_tools in cases:
            with self.subTest(request=request):
                job, _saved, _on_error = self.make_memo_job(request)
                offered_tool_names: list[str] = []

                def stream(
                    _messages,
                    _model,
                    *,
                    tools=None,
                    captured_names=offered_tool_names,
                    **_kwargs,
                ):
                    captured_names.extend(
                        tool["function"]["name"] for tool in (tools or [])
                    )
                    yield "回答します。"

                self.run_job(job, stream, web_search=True)

                if expect_external_tools:
                    self.assertIn("web_search", offered_tool_names)
                    self.assertIn("read_web_page", offered_tool_names)
                else:
                    self.assertNotIn("web_search", offered_tool_names)
                    self.assertNotIn("read_web_page", offered_tool_names)
                    self.assertNotIn("get_evidence", offered_tool_names)

    # 日本語: メモ一覧の後の呼び出しが1度拒否されても、ツール付きの引き直しで本文を読みに行き、
    # 拒否の診断（理由・ツール名・提示していたツール）だけを記録することを検証します。
    # English: Verify a call rejected once after listing memos is resampled with tools and still
    # reads the body, and that only the diagnosis (reason, tool, offered tools) is recorded.
    def test_rejected_memo_call_is_resampled_with_tools_and_reads_the_body(self):
        memo = McpMemoDetail(
            id=105,
            title="新製品の準備メモ",
            revision=1,
            content="新製品の発売予定日は2026年10月12日。",
        )
        listing = McpMemoListResult(total=1, memos=[McpMemoSummary(id=105, title=memo.title, revision=1)])
        offered: list[bool] = []

        def stream(messages, _model, *, tools=None, **_kwargs):
            offered.append(bool(tools))
            step = len(offered)
            if step == 1:
                yield json.dumps([tool_call("memo_list")])
            elif step == 2:
                raise LlmToolSchemaError(
                    "Groq API rejected the model's tool call against the tool schema.",
                    reason="schema_mismatch",
                    tool_name="memo_read",
                )
            elif step == 3:
                yield json.dumps([tool_call("memo_read", memo_id=105)])
            else:
                read_results = [m["content"] for m in messages if m.get("role") == "tool"]
                self.assertTrue(any("2026年10月12日" in content for content in read_results))
                yield "発売予定日は2026年10月12日です。"

        job, saved, _on_error = self.make_memo_job("私のメモを日本語で要約してください。")
        with (
            patch("services.chat_workspace_tools.memo.list_memos", return_value=listing),
            patch("services.chat_workspace_tools.memo.get_memo", return_value=memo),
        ):
            self.run_job(job, stream)

        self.assertEqual(offered, [True, True, True, True])
        self.assertEqual(terminal_event(job).event, "done")
        self.assertIn("2026年10月12日", saved.call_args.args[0])
        telemetry = job._telemetry
        self.assertEqual(telemetry.tool_schema_retries, 1)
        self.assertEqual(telemetry.tool_schema_recoveries, 0)
        self.assertEqual(telemetry.workspace_tool_results, ["memo_list:ok", "memo_read:ok"])
        self.assertEqual(len(telemetry.tool_schema_rejections), 1)
        rejection = telemetry.tool_schema_rejections[0]
        self.assertEqual(rejection["reason"], "schema_mismatch")
        self.assertEqual(rejection["tool"], "memo_read")
        self.assertTrue(rejection["tool_offered"])
        self.assertIn("memo_read", rejection["offered_tools"])
        self.assertNotIn("2026", json.dumps(telemetry.as_log_extra(), ensure_ascii=False))

    # 日本語: 本文を1文字も書けなかった失敗は、これまで通りエラーとして通知されることを検証します。
    # English: Verify a failure that produced no body at all is still reported as an error.
    def test_failure_without_any_body_still_reports_an_error(self):
        def stream(_messages, _model, **_kwargs):
            raise LlmUpstreamServiceError("Groq API reported a mid-stream failure.")

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

    # 日本語: バッファにタグ無しの封筒 JSON しか無いまま落ちたターンは、それを回答として救出しません。
    # English: A turn that fails holding only an untagged envelope JSON does not salvage it.
    def test_failure_does_not_salvage_an_untagged_envelope(self):
        def stream(_messages, _model, **_kwargs):
            yield UNTAGGED_ENVELOPE
            raise LlmUpstreamServiceError("Groq API reported a mid-stream failure.")

        job, saved, on_error = self.make_job()
        self.run_job(job, stream)

        self.assertEqual(terminal_event(job).event, "error")
        on_error.assert_called_once()
        saved.assert_not_called()
        self.assertEqual(job._telemetry.salvaged_partial_answers, 0)
        self.assertEqual(job._telemetry.untagged_turn_state_recoveries, 1)

    # 日本語: 停止時の未配信バッファがタグ無しの封筒 JSON だけなら、保存せず中断だけを通知します。
    # English: On a stop, an undelivered buffer holding only an untagged envelope JSON is not
    # persisted; only the abort is signalled.
    def test_cancel_does_not_persist_an_untagged_envelope(self):
        job, saved, _on_error = self.make_job()
        job._pending_stream_chunks = [UNTAGGED_ENVELOPE]

        job.cancel()

        self.assertEqual(terminal_event(job).event, "aborted")
        self.assertEqual(terminal_event(job).payload, {})
        saved.assert_not_called()
        self.assertEqual(job._telemetry.untagged_turn_state_recoveries, 1)


    # 日本語: 停止が先にバッファを取り出した判断は、回答ステップ側でタグ無し封筒を数え直しません。
    # English: When a stop already took the buffer, the answer step does not count the same
    # untagged envelope again.
    def test_untagged_envelope_taken_by_cancel_is_counted_once(self):
        job, saved, _on_error = self.make_job()
        state = job._build_turn_run_state()
        step_chunks = [UNTAGGED_ENVELOPE]
        job._pending_stream_chunks = step_chunks

        job.cancel()
        job._finish_answer_step(state, [], None, step_chunks)

        self.assertEqual(job._telemetry.untagged_turn_state_recoveries, 1)
        self.assertEqual(state.turn_state.objective, "説明して")
        self.assertEqual(state.chunks, [])
        saved.assert_not_called()


if __name__ == "__main__":
    unittest.main()
