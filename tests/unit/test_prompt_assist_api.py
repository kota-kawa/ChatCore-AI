import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.chat.tasks import (
    AI_AGENT_HISTORY_MAX_MESSAGES,
    AI_AGENT_SYSTEM_PROMPT,
    _build_ai_agent_messages,
    ai_agent,
    prompt_assist,
)
from services.llm import LlmProviderError
from services.memo_agent_actions import MemoAgentContext
from services.request_models import AiAgentRequest
from tests.helpers.request_helpers import build_request


async def _collect_sse_done(response) -> dict:
    """StreamingResponse の body_iterator を読み進め、done/action_plan/error イベントのペイロードを返す。"""
    body = b""
    # 日本語: 非同期の対象データを順番に処理します。
    # English: Process each asynchronous target item in order.
    async for chunk in response.body_iterator:
        body += chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
    # 日本語: 各対象データを順に処理し、検証を行います。
    for block in body.decode("utf-8").split("\n\n"):
        event_type = "message"
        data = ""
        for line in block.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                data = line[6:].strip()
        if data and event_type in ("done", "action_plan", "error"):
            return json.loads(data)
    return {}


async def _collect_sse_events(response) -> list[tuple[str, dict]]:
    body = b""
    # 日本語: 非同期の対象データを順番に処理します。
    # English: Process each asynchronous target item in order.
    async for chunk in response.body_iterator:
        body += chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")

    events = []
    # 日本語: 各対象データを順に処理し、検証を行います。
    for block in body.decode("utf-8").split("\n\n"):
        event_type = "message"
        data = ""
        for line in block.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                data = line[6:].strip()
        if data:
            events.append((event_type, json.loads(data)))
    return events


def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/prompt-assist",
        json_body=json_body,
        session=session,
    )


def make_ai_agent_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/ai-agent",
        json_body=json_body,
        session=session,
    )


# 日本語: Prompt Assist Apiの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Prompt Assist Api.
class PromptAssistApiTestCase(unittest.TestCase):
    # 日本語: aiagentシステムプロンプト要求するplainユーザー向けのlanguageことを検証します。
    # English: Verify that ai agent system prompt requires plain user facing language.
    def test_ai_agent_system_prompt_requires_plain_user_facing_language(self):
        self.assertIn(
            "plain, easy words that everyone from children to older adults can understand",
            AI_AGENT_SYSTEM_PROMPT,
        )
        self.assertIn(
            "code-derived names such as variable names, function names, class names",
            AI_AGENT_SYSTEM_PROMPT,
        )
        self.assertIn(
            "do not copy them as-is; rephrase them in words for the user",
            AI_AGENT_SYSTEM_PROMPT,
        )
        self.assertIn("Prefer the words shown on screen", AI_AGENT_SYSTEM_PROMPT)
        self.assertIn("Never create clickable URLs", AI_AGENT_SYSTEM_PROMPT)
        self.assertIn("full URL verbatim in inline code", AI_AGENT_SYSTEM_PROMPT)
        self.assertIn("```chatcore-copy fenced block", AI_AGENT_SYSTEM_PROMPT)

    # 日本語: Chacoの自己認識とキャラクターに合う口調がシステムプロンプトに含まれることを検証します。
    # English: Verify that the system prompt defines Chaco's identity and character-appropriate voice.
    def test_ai_agent_system_prompt_defines_chaco_identity_and_voice(self):
        self.assertIn("Your name is Chaco", AI_AGENT_SYSTEM_PROMPT)
        self.assertIn("write and say your name as チャコ", AI_AGENT_SYSTEM_PROMPT)
        self.assertIn("friendly support-agent mascot", AI_AGENT_SYSTEM_PROMPT)
        self.assertIn("warm, gentle, cheerful, and encouraging tone", AI_AGENT_SYSTEM_PROMPT)
        self.assertIn("do not use baby talk, excessive emojis, forced catchphrases", AI_AGENT_SYSTEM_PROMPT)

    # 日本語: プロンプトアシスト要求するログインことを検証します。
    # English: Verify that prompt assist requires login.
    def test_prompt_assist_requires_login(self):
        request = make_request(
            {
                "target": "task_modal",
                "action": "generate_draft",
                "fields": {
                    "title": "メール返信",
                    "prompt_content": "丁寧な返信テンプレートを作りたい",
                },
            },
            session={},
        )

        response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "ログインが必要です")

    # 日本語: プロンプトアシスト返却するsuggestionsことを検証します。
    # English: Verify that prompt assist returns suggestions.
    def test_prompt_assist_returns_suggestions(self):
        request = make_request(
            {
                "target": "task_modal",
                "action": "generate_draft",
                "fields": {
                    "title": "メール返信",
                    "prompt_content": "丁寧な返信テンプレートを作りたい",
                },
            },
            session={"user_id": 1},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.tasks._consume_prompt_assist_limits", return_value=(True, None)):
            with patch("blueprints.chat.tasks.consume_llm_daily_quota", return_value=(True, 299, 300)):
                with patch(
                    "blueprints.chat.tasks.create_prompt_assist_payload",
                    return_value={
                        "summary": "AIが下書きを作成しました。",
                        "warnings": [],
                        "suggested_fields": {
                            "title": "丁寧なメール返信テンプレート",
                            "prompt_content": "顧客への丁寧な返信文を作成してください。",
                        },
                        "model": "openai/gpt-oss-120b",
                    },
                ):
                    response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["suggested_fields"]["title"], "丁寧なメール返信テンプレート")
        self.assertEqual(payload["model"], "openai/gpt-oss-120b")

    # 日本語: ゲストに対して、aiagent返却するgptoss120bレスポンスことを検証します。
    # English: Verify that ai agent returns gpt oss 120b response for guest.
    def test_ai_agent_returns_gpt_oss_120b_response_for_guest(self):
        request = make_ai_agent_request(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "このプロンプトを短く改善して",
                    }
                ]
            },
            session={},
        )

        async def _run():
            # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
            with patch("blueprints.chat.tasks._consume_ai_agent_limits", return_value=(True, None)) as mock_limits:
                with patch("blueprints.chat.tasks.consume_ai_agent_monthly_quota", return_value=(True, 999, 1000)):
                    with patch("blueprints.chat.tasks.classify_intent", return_value="direct"):
                        with patch("blueprints.chat.tasks.get_llm_response", return_value="改善案です。") as mock_llm:
                            response = await ai_agent(request)
                            payload = await _collect_sse_done(response)
            return response, payload, mock_limits, mock_llm

        response, payload, mock_limits, mock_llm = asyncio.run(_run())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["response"], "改善案です。")
        self.assertEqual(payload["model"], "openai/gpt-oss-120b")
        self.assertEqual(mock_llm.call_args.args[1], "openai/gpt-oss-120b")
        self.assertTrue(mock_limits.call_args.args[1].startswith("guest:"))

    def test_ai_agent_uses_the_same_20_message_history_window(self):
        payload = AiAgentRequest(
            messages=[
                {"role": "user" if index % 2 == 0 else "assistant", "content": f"message-{index}"}
                for index in range(AI_AGENT_HISTORY_MAX_MESSAGES)
            ]
        )

        messages = _build_ai_agent_messages(payload)

        self.assertEqual(AI_AGENT_HISTORY_MAX_MESSAGES, 20)
        self.assertEqual(len(messages), 21)
        self.assertEqual(messages[1]["content"], "message-0")
        self.assertEqual(messages[-1]["content"], "message-19")

    # 日本語: doneの前、aiagentstreamsprogressことを検証します。
    # English: Verify that ai agent streams progress before done.
    def test_ai_agent_streams_progress_before_done(self):
        request = make_ai_agent_request(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "相談です",
                    }
                ]
            },
            session={},
        )

        async def _run():
            # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
            with patch("blueprints.chat.tasks._consume_ai_agent_limits", return_value=(True, None)):
                with patch("blueprints.chat.tasks.consume_ai_agent_monthly_quota", return_value=(True, 999, 1000)):
                    with patch("blueprints.chat.tasks.classify_intent", return_value="direct"):
                        with patch("blueprints.chat.tasks.get_llm_response", return_value="回答です。"):
                            response = await ai_agent(request)
                            events = await _collect_sse_events(response)
            return response, events

        response, events = asyncio.run(_run())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[0], ("progress", {"message": "依頼内容を確認中..."}))
        self.assertIn(("progress", {"message": "回答を生成中..."}), events)
        self.assertEqual(events[-1][0], "done")

    def test_ai_agent_localizes_progress_for_english_ui(self):
        request = make_ai_agent_request(
            {"messages": [{"role": "user", "content": "How do I use this page?"}]},
            session={"preferred_locale": "en"},
        )

        async def _run():
            with patch("blueprints.chat.tasks._consume_ai_agent_limits", return_value=(True, None)):
                with patch("blueprints.chat.tasks.consume_ai_agent_monthly_quota", return_value=(True, 999, 1000)):
                    with patch("blueprints.chat.tasks.classify_intent", return_value="direct"):
                        with patch("blueprints.chat.tasks.get_llm_response", return_value="Here is how."):
                            response = await ai_agent(request)
                            return await _collect_sse_events(response)

        events = asyncio.run(_run())

        self.assertEqual(events[0], ("progress", {"message": "Checking your request..."}))
        self.assertIn(("progress", {"message": "Generating a response..."}), events)
        self.assertEqual(events[-1][1]["response"], "Here is how.")

    # 日本語: aiagentactionplanuses現在domコンテキストことを検証します。
    # English: Verify that ai agent action plan uses current dom context.
    def test_ai_agent_action_plan_uses_current_dom_context(self):
        request = make_ai_agent_request(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "プロンプトを検索して",
                    }
                ],
                "current_page": "/prompt_share",
                "current_dom": "1. selector=#searchInput; tag=input; placeholder=キーワードでプロンプトを検索\n"
                "2. selector=#searchButton; tag=button; aria-label=検索を実行する",
            },
            session={},
        )

        async def _run():
            # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
            with patch("blueprints.chat.tasks._consume_ai_agent_limits", return_value=(True, None)):
                with patch("blueprints.chat.tasks.consume_ai_agent_monthly_quota", return_value=(True, 999, 1000)):
                    with patch("blueprints.chat.tasks.classify_intent", return_value="action"):
                        with patch(
                            "blueprints.chat.tasks.get_llm_response",
                            return_value=(
                                '{"description":"プロンプト検索を実行します",'
                                '"steps":[{"action":"click","selector":"#searchButton","description":"検索ボタンを押す"}]}'
                            ),
                        ) as mock_llm:
                            response = await ai_agent(request)
                            payload = await _collect_sse_done(response)
            return response, payload, mock_llm

        response, payload, mock_llm = asyncio.run(_run())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["description"], "プロンプト検索を実行します")
        self.assertEqual(payload["steps"][0]["selector"], "#searchButton")
        self.assertEqual(payload["model"], "openai/gpt-oss-120b")
        self.assertIn("#searchInput", mock_llm.call_args.args[0][0]["content"])
        self.assertIn("ChatCore 機能カタログ", mock_llm.call_args.args[0][0]["content"])

    # 日本語: メモ経路のテストで共通の依存（制限・メモ文脈・意図分類・LLM）を差し替えて実行し、SSEイベントを返します。
    # English: Run a memo-scoped request with the shared dependencies (limits, memo context, intent, LLMs) patched.
    def _run_memo_agent(self, message, memo_context, *, intent, edit_llm, answer_llm=None):
        request = make_ai_agent_request(
            {
                "messages": [{"role": "user", "content": message}],
                "current_page": "/memo",
                "memo_id": 12,
            },
            session={"user_id": 7},
        )

        async def _run():
            # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
            # English: Mock dependencies or context to configure the test environment.
            with patch("blueprints.chat.tasks._consume_ai_agent_limits", return_value=(True, None)):
                with patch("blueprints.chat.tasks.consume_ai_agent_monthly_quota", return_value=(True, 999, 1000)):
                    with patch(
                        "blueprints.chat.tasks._build_ai_agent_memo_context",
                        new_callable=AsyncMock,
                        return_value=memo_context,
                    ):
                        with patch("blueprints.chat.tasks.classify_memo_intent", return_value=intent):
                            with patch("services.memo_agent_actions.get_llm_response", **edit_llm) as mock_edit:
                                with patch(
                                    "blueprints.chat.tasks.get_llm_response",
                                    **(answer_llm or {"return_value": "回答です。"}),
                                ) as mock_answer:
                                    response = await ai_agent(request)
                                    events = await _collect_sse_events(response)
            return response, events, mock_edit, mock_answer

        return asyncio.run(_run())

    # 日本語: メモの編集依頼に対して、memo_editステップを含むアクションプランが返ることを検証します。
    # English: Verify that a memo edit request yields an action plan containing a memo_edit step.
    def test_ai_agent_memo_edit_request_returns_action_plan(self):
        response, events, mock_edit, mock_answer = self._run_memo_agent(
            "誤字脱字を修正して",
            MemoAgentContext(
                prompt_context="【現在開いているメモ】\nタイトル: 会議メモ\n\n本文:\n誤字のある本文",
                stored_body="誤字のある本文",
                body_truncated=False,
            ),
            intent="edit",
            edit_llm={
                "return_value": (
                    '{"description":"誤字を修正します",'
                    '"steps":[{"action":"memo_edit","description":"誤字を直した本文へ置き換えます",'
                    '"content":"修正済みの本文"}]}'
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(("progress", {"message": "編集案を作成中..."}), events)
        self.assertEqual(events[-1][0], "action_plan")
        plan = events[-1][1]
        self.assertEqual(plan["description"], "誤字を修正します")
        self.assertEqual(plan["steps"][0]["action"], "memo_edit")
        self.assertEqual(plan["steps"][0]["content"], "修正済みの本文")
        self.assertEqual(plan["model"], "openai/gpt-oss-120b")
        # 編集計画の生成にメモ本文が参照情報として渡されていることを確認する
        # Confirm the memo body was passed as reference context for plan generation
        self.assertIn("誤字のある本文", mock_edit.call_args.args[0][0]["content"])
        mock_answer.assert_not_called()

    # 日本語: 部分置換の編集計画は、全文ではなく edits としてフロントへ送られることを検証します。
    # English: Verify a partial-edit plan reaches the frontend as edits rather than a full body.
    def test_ai_agent_memo_partial_edit_returns_edits(self):
        response, events, mock_edit, _ = self._run_memo_agent(
            "誤字を直して",
            MemoAgentContext(
                prompt_context="[Memo currently open]\nBody:\n会議は月よう日です。\n議題は予算です。",
                stored_body="会議は月よう日です。\r\n議題は予算です。",
                body_truncated=False,
            ),
            intent="edit",
            edit_llm={
                "return_value": json.dumps({
                    "description": "誤字を直します",
                    "steps": [{
                        "action": "memo_edit",
                        "description": "曜日の表記を直します",
                        "edits": [{"old_string": "月よう日", "new_string": "月曜日"}],
                    }],
                }, ensure_ascii=False),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1][0], "action_plan")
        step = events[-1][1]["steps"][0]
        self.assertEqual(step["edits"], [{"old_string": "月よう日", "new_string": "月曜日"}])
        self.assertNotIn("content", step)
        mock_edit.assert_called_once()

    # 日本語: old_string が本文に見つからない計画は、理由を添えて1回だけ作り直させることを検証します。
    # English: Verify a plan whose old_string is missing from the body is regenerated once with the reason.
    def test_ai_agent_memo_partial_edit_regenerates_once_on_mismatch(self):
        def plan(old_string):
            return json.dumps({
                "description": "誤字を直します",
                "steps": [{
                    "action": "memo_edit",
                    "description": "曜日を直します",
                    "edits": [{"old_string": old_string, "new_string": "月曜日"}],
                }],
            }, ensure_ascii=False)

        response, events, mock_edit, mock_answer = self._run_memo_agent(
            "誤字を直して",
            MemoAgentContext(
                prompt_context="[Memo currently open]\nBody:\n会議は月よう日です。",
                stored_body="会議は月よう日です。",
                body_truncated=False,
            ),
            intent="edit",
            edit_llm={"side_effect": [plan("月よう日。"), plan("月よう日")]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1][0], "action_plan")
        self.assertEqual(events[-1][1]["steps"][0]["edits"][0]["old_string"], "月よう日")
        self.assertEqual(mock_edit.call_count, 2)
        feedback = mock_edit.call_args_list[1].args[0][-1]["content"]
        self.assertIn("edits[0].old_string was not found in the body", feedback)
        mock_answer.assert_not_called()

    # 日本語: 作り直しても照合できなければ、通常のQA回答へ切り替えることを検証します。
    # English: Verify the route falls back to a QA answer when the regenerated plan still does not match.
    def test_ai_agent_memo_edit_falls_back_to_answer_after_failed_regeneration(self):
        unmatched = json.dumps({
            "description": "誤字を直します",
            "steps": [{
                "action": "memo_edit",
                "description": "曜日を直します",
                "edits": [{"old_string": "火曜日", "new_string": "水曜日"}],
            }],
        }, ensure_ascii=False)

        response, events, mock_edit, mock_answer = self._run_memo_agent(
            "誤字を直して",
            MemoAgentContext(
                prompt_context="[Memo currently open]\nBody:\n会議は月曜日です。",
                stored_body="会議は月曜日です。",
                body_truncated=False,
            ),
            intent="edit",
            edit_llm={"side_effect": [unmatched, unmatched]},
            answer_llm={"return_value": "代わりの回答です。"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1], ("done", {"response": "代わりの回答です。", "model": "openai/gpt-oss-120b"}))
        self.assertEqual(mock_edit.call_count, 2)
        mock_answer.assert_called_once()

    # 日本語: メモへの質問はこれまで通りdoneイベントで直接回答が返ることを検証します。
    # English: Verify that memo questions still return a direct answer via the done event.
    def test_ai_agent_memo_question_still_returns_answer(self):
        response, events, mock_edit, _ = self._run_memo_agent(
            "このメモを要約して",
            MemoAgentContext(
                prompt_context="【現在開いているメモ】\n本文:\nテスト本文",
                stored_body="テスト本文",
                body_truncated=False,
            ),
            intent="qa",
            edit_llm={"return_value": "使われない"},
            answer_llm={"return_value": "要約です。"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(events[-1][1]["response"], "要約です。")
        mock_edit.assert_not_called()

    # 日本語: 編集計画を生成できない（計画を作らない）応答は、作り直さずに通常回答へフォールバックすることを検証します。
    # English: Verify a reply without a plan falls back to a normal answer without a regeneration.
    def test_ai_agent_memo_edit_falls_back_to_answer_when_plan_invalid(self):
        response, events, mock_edit, mock_answer = self._run_memo_agent(
            "本文を書き直して",
            MemoAgentContext(
                prompt_context="【現在開いているメモ】\n本文:\nテスト本文",
                stored_body="テスト本文",
                body_truncated=False,
            ),
            intent="edit",
            edit_llm={"return_value": "編集計画を作れませんでした。"},
            answer_llm={"return_value": "代わりの回答です。"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(events[-1][1]["response"], "代わりの回答です。")
        mock_edit.assert_called_once()
        mock_answer.assert_called_once()

    # 日本語: 本文を切り詰めたメモでも、見えている範囲への部分置換は保存済みの全文で照合して提案できることを検証します。
    # English: Verify a truncated memo still gets a partial-edit plan, matched against the full stored body.
    def test_ai_agent_memo_partial_edit_allowed_when_body_truncated(self):
        response, events, mock_edit, mock_answer = self._run_memo_agent(
            "冒頭の誤字を直して",
            MemoAgentContext(
                prompt_context=(
                    "[Memo currently open]\nBody:\n長い本文の先頭部分\n\n"
                    "(part of the body was omitted because it is long)"
                ),
                stored_body="長い本文の先頭部分\n見えていない末尾の段落",
                body_truncated=True,
            ),
            intent="edit",
            edit_llm={
                "return_value": json.dumps({
                    "description": "冒頭を直します",
                    "steps": [{
                        "action": "memo_edit",
                        "description": "冒頭の表記を直します",
                        "edits": [{"old_string": "先頭部分", "new_string": "冒頭部分"}],
                    }],
                }, ensure_ascii=False),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(("progress", {"message": "編集案を作成中..."}), events)
        self.assertEqual(events[-1][0], "action_plan")
        self.assertEqual(events[-1][1]["steps"][0]["edits"][0]["new_string"], "冒頭部分")
        self.assertIn('Use "edits" only', mock_edit.call_args.args[0][0]["content"])
        mock_answer.assert_not_called()

    # 日本語: 本文を切り詰めたメモでは全文置換を採用せず、作り直しでも直らなければQA回答へ切り替えることを検証します。
    # English: Verify a truncated memo never takes a full replacement and falls back to QA if the retry keeps one.
    def test_ai_agent_memo_full_replacement_refused_when_body_truncated(self):
        full_replacement = (
            '{"description":"書き直します","steps":[{"action":"memo_edit",'
            '"description":"本文を置き換えます","content":"短くなった本文"}]}'
        )

        response, events, mock_edit, mock_answer = self._run_memo_agent(
            "本文を書き直して",
            MemoAgentContext(
                prompt_context=(
                    "[Memo currently open]\nBody:\n長い本文の先頭部分\n\n"
                    "(part of the body was omitted because it is long)"
                ),
                stored_body="長い本文の先頭部分\n見えていない末尾の段落",
                body_truncated=True,
            ),
            intent="edit",
            edit_llm={"side_effect": [full_replacement, full_replacement]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(mock_edit.call_count, 2)
        self.assertIn("The body is truncated", mock_edit.call_args_list[1].args[0][-1]["content"])
        mock_answer.assert_called_once()

    # 日本語: monthlyクォータ超過のとき、aiagent返却する429ことを検証します。
    # English: Verify that ai agent returns 429 when monthly quota exceeded.
    def test_ai_agent_returns_429_when_monthly_quota_exceeded(self):
        request = make_ai_agent_request(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "相談です",
                    }
                ]
            },
            session={"user_id": 1},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.tasks._consume_ai_agent_limits", return_value=(True, None)):
            with patch("blueprints.chat.tasks.consume_ai_agent_monthly_quota", return_value=(False, 0, 1000)):
                with patch("blueprints.chat.tasks.get_llm_response") as mock_llm:
                    response = asyncio.run(ai_agent(request))

        self.assertEqual(response.status_code, 429)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("上限", payload["error"])
        mock_llm.assert_not_called()

    # 日本語: 1日のクォータ超過のとき、プロンプトアシスト返却する429ことを検証します。
    # English: Verify that prompt assist returns 429 when daily quota exceeded.
    def test_prompt_assist_returns_429_when_daily_quota_exceeded(self):
        request = make_request(
            {
                "target": "task_modal",
                "action": "generate_draft",
                "fields": {
                    "title": "メール返信",
                    "prompt_content": "丁寧な返信テンプレートを作りたい",
                },
            },
            session={"user_id": 1},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.tasks._consume_prompt_assist_limits", return_value=(True, None)):
            with patch(
                "blueprints.chat.tasks.consume_llm_daily_quota",
                return_value=(False, 0, 300),
            ):
                with patch("blueprints.chat.tasks.create_prompt_assist_payload") as mock_create:
                    response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.headers.get("Retry-After"))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("上限", payload["error"])
        mock_create.assert_not_called()

    # 日本語: レート制限のとき、プロンプトアシスト返却する429ことを検証します。
    # English: Verify that prompt assist returns 429 when rate limited.
    def test_prompt_assist_returns_429_when_rate_limited(self):
        request = make_request(
            {
                "target": "task_modal",
                "action": "generate_draft",
                "fields": {
                    "title": "メール返信",
                    "prompt_content": "丁寧な返信テンプレートを作りたい",
                },
            },
            session={"user_id": 1},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "blueprints.chat.tasks._consume_prompt_assist_limits",
            return_value=(False, "AI補助の試行回数が多すぎます。10秒ほど待ってから再試行してください。"),
        ):
            with patch("blueprints.chat.tasks.create_prompt_assist_payload") as mock_create:
                response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "10")
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("多すぎます", payload["error"])
        mock_create.assert_not_called()

    # 日本語: bodyを使用しない場合、プロンプトアシスト拒否するimproveことを検証します。
    # English: Verify that prompt assist rejects improve without body.
    def test_prompt_assist_rejects_improve_without_body(self):
        request = make_request(
            {
                "target": "task_modal",
                "action": "improve",
                "fields": {
                    "title": "メール返信",
                    "prompt_content": "   ",
                },
            },
            session={"user_id": 1},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.tasks._consume_prompt_assist_limits", return_value=(True, None)):
            with patch("blueprints.chat.tasks.consume_llm_daily_quota", return_value=(True, 299, 300)):
                response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "本文を入力してからAI補助を実行してください。")

    # 日本語: llm失敗における、プロンプトアシスト返却するretryableエラーことを検証します。
    # English: Verify that prompt assist returns retryable error on llm failure.
    def test_prompt_assist_returns_retryable_error_on_llm_failure(self):
        request = make_request(
            {
                "target": "shared_prompt_modal",
                "action": "generate_examples",
                "fields": {
                    "title": "学習計画",
                    "content": "学習計画を1週間分作るプロンプト",
                },
            },
            session={"user_id": 1},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.chat.tasks._consume_prompt_assist_limits", return_value=(True, None)):
            with patch("blueprints.chat.tasks.consume_llm_daily_quota", return_value=(True, 299, 300)):
                with patch(
                    "blueprints.chat.tasks.create_prompt_assist_payload",
                    side_effect=LlmProviderError("boom"),
                ):
                    response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 502)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "AI補助の取得に失敗しました。時間をおいて再試行してください。")


if __name__ == "__main__":
    unittest.main()
