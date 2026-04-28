import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.tasks import AI_AGENT_SYSTEM_PROMPT, ai_agent, prompt_assist
from services.llm import LlmProviderError
from tests.helpers.request_helpers import build_request


async def _collect_sse_done(response) -> dict:
    """StreamingResponse の body_iterator を読み進め、done/action_plan/error イベントのペイロードを返す。"""
    body = b""
    async for chunk in response.body_iterator:
        body += chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
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
    async for chunk in response.body_iterator:
        body += chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")

    events = []
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


class PromptAssistApiTestCase(unittest.TestCase):
    def test_ai_agent_system_prompt_requires_plain_user_facing_language(self):
        self.assertIn("子供から高齢者まで分かる", AI_AGENT_SYSTEM_PROMPT)
        self.assertIn("変数名、関数名、クラス名", AI_AGENT_SYSTEM_PROMPT)
        self.assertIn("コード由来の名前は回答に出さない", AI_AGENT_SYSTEM_PROMPT)
        self.assertIn("画面上の言葉を優先", AI_AGENT_SYSTEM_PROMPT)

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
            with patch("blueprints.chat.tasks._consume_ai_agent_limits", return_value=(True, None)) as mock_limits:
                with patch("blueprints.chat.tasks.consume_llm_daily_quota", return_value=(True, 299, 300)):
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
            with patch("blueprints.chat.tasks._consume_ai_agent_limits", return_value=(True, None)):
                with patch("blueprints.chat.tasks.consume_llm_daily_quota", return_value=(True, 299, 300)):
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
            with patch("blueprints.chat.tasks._consume_ai_agent_limits", return_value=(True, None)):
                with patch("blueprints.chat.tasks.consume_llm_daily_quota", return_value=(True, 299, 300)):
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
        self.assertIn("#searchInput", mock_llm.call_args.args[0][0]["content"])
        self.assertIn("ChatCore 機能カタログ", mock_llm.call_args.args[0][0]["content"])

    def test_ai_agent_returns_429_when_daily_quota_exceeded(self):
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

        with patch("blueprints.chat.tasks._consume_ai_agent_limits", return_value=(True, None)):
            with patch("blueprints.chat.tasks.consume_llm_daily_quota", return_value=(False, 0, 300)):
                with patch("blueprints.chat.tasks.get_llm_response") as mock_llm:
                    response = asyncio.run(ai_agent(request))

        self.assertEqual(response.status_code, 429)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("上限", payload["error"])
        mock_llm.assert_not_called()

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

        with patch("blueprints.chat.tasks._consume_prompt_assist_limits", return_value=(True, None)):
            with patch("blueprints.chat.tasks.consume_llm_daily_quota", return_value=(True, 299, 300)):
                response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "本文を入力してからAI補助を実行してください。")

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
