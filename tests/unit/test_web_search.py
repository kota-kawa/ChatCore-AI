import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services import web_search


class WebSearchServiceTestCase(unittest.TestCase):
    def setUp(self):
        web_search._search_cache.clear()

    def test_decide_web_search_uses_llm_json_decision(self):
        messages = [{"role": "user", "content": "今日のOpenAIの最新ニュースを調べて"}]

        with patch.object(
            web_search,
            "get_llm_response",
            return_value='{"should_search": true, "query": "OpenAI latest news", "freshness": "pd", "reason": "current news"}',
        ):
            decision = web_search.decide_web_search(messages, "gemini-2.5-flash")

        self.assertTrue(decision.should_search)
        self.assertEqual(decision.query, "OpenAI latest news")
        self.assertEqual(decision.freshness, "pd")

    def test_decide_web_search_does_not_search_when_planner_fails(self):
        messages = [{"role": "user", "content": "React 19の最新情報を検索して"}]

        with patch.object(web_search, "get_llm_response", side_effect=RuntimeError("down")):
            decision = web_search.decide_web_search(messages, "gemini-2.5-flash")

        self.assertFalse(decision.should_search)
        self.assertEqual(decision.reason, "web search planner unavailable")

    def test_decide_web_search_uses_planner_for_plain_greeting(self):
        messages = [{"role": "user", "content": "こんにちは"}]

        with patch.object(
            web_search,
            "get_llm_response",
            return_value='{"should_search": false, "query": "", "freshness": "", "reason": "greeting"}',
        ) as mock_llm:
            decision = web_search.decide_web_search(messages, "gemini-2.5-flash")

        self.assertFalse(decision.should_search)
        mock_llm.assert_called_once()

    def test_decide_web_search_consults_planner_for_substantive_normal_message(self):
        messages = [{"role": "user", "content": "日本で法人を設立する時の注意点を教えてください"}]

        with patch.object(
            web_search,
            "get_llm_response",
            return_value='{"should_search": true, "query": "日本 法人設立 注意点 最新", "freshness": "py", "reason": "legal and procedural details"}',
        ) as mock_llm:
            decision = web_search.decide_web_search(messages, "gemini-2.5-flash")

        self.assertTrue(decision.should_search)
        self.assertIn("法人設立", decision.query)
        mock_llm.assert_called_once()

    def test_decide_web_search_includes_task_system_context_for_task_card_launch(self):
        messages = [
            {
                "role": "system",
                "content": "<task_contract><task_name>市場調査</task_name><task_instruction>最新情報を調べて競合比較してください。</task_instruction></task_contract>",
            },
            {"role": "user", "content": "【タスク】市場調査\n【状況・作業環境】新しいCRMを検討しています"},
        ]

        with patch.object(
            web_search,
            "get_llm_response",
            return_value='{"should_search": true, "query": "CRM 最新 比較", "freshness": "pm", "reason": "active task requires research"}',
        ) as mock_llm:
            decision = web_search.decide_web_search(messages, "gemini-2.5-flash")

        planner_context = mock_llm.call_args.args[0][1]["content"]
        self.assertTrue(decision.should_search)
        self.assertIn("実行中タスクシステム", planner_context)
        self.assertIn("最新情報を調べて競合比較", planner_context)

    def test_decide_web_search_uses_planner_for_pure_writing_task(self):
        messages = [{"role": "user", "content": "短い自己紹介文を書いて"}]

        with patch.object(
            web_search,
            "get_llm_response",
            return_value='{"should_search": false, "query": "", "freshness": "", "reason": "pure writing"}',
        ) as mock_llm:
            decision = web_search.decide_web_search(messages, "gemini-2.5-flash")

        self.assertFalse(decision.should_search)
        mock_llm.assert_called_once()

    def test_search_brave_llm_context_parses_sources(self):
        response = MagicMock()
        response.json.return_value = {
            "grounding": {
                "generic": [
                    {
                        "url": "https://example.com/a",
                        "title": "Example A",
                        "snippets": ["Snippet one", "Snippet two"],
                    }
                ],
                "map": [],
            },
            "sources": {
                "https://example.com/a": {
                    "hostname": "example.com",
                    "age": ["2026-04-30"],
                }
            },
        }
        response.raise_for_status.return_value = None

        with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}, clear=False):
            with patch.object(web_search.requests, "get", return_value=response) as mock_get:
                result = web_search.search_brave_llm_context("example query", freshness="pw")

        self.assertEqual(result.query, "example query")
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0].hostname, "example.com")
        self.assertEqual(result.sources[0].snippets, ("Snippet one", "Snippet two"))
        self.assertEqual(mock_get.call_args.args[0], web_search.BRAVE_LLM_CONTEXT_URL)
        self.assertEqual(mock_get.call_args.kwargs["headers"]["X-Subscription-Token"], "test-key")
        self.assertEqual(mock_get.call_args.kwargs["params"]["freshness"], "pw")
        self.assertEqual(mock_get.call_args.kwargs["params"]["search_lang"], "en")

    def test_search_brave_llm_context_uses_brave_jp_language_code_for_japanese(self):
        response = MagicMock()
        response.json.return_value = {"grounding": {"generic": [], "map": []}, "sources": {}}
        response.raise_for_status.return_value = None

        with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}, clear=False):
            with patch.object(web_search.requests, "get", return_value=response) as mock_get:
                web_search.search_brave_llm_context("今日のニュース", freshness="pd")

        self.assertEqual(mock_get.call_args.kwargs["params"]["search_lang"], "jp")

    def test_search_brave_llm_context_blocks_when_monthly_quota_exceeded(self):
        with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}, clear=False):
            with patch.object(
                web_search,
                "consume_brave_web_search_monthly_quota",
                return_value=(False, 0, 500),
            ):
                with patch.object(web_search, "get_seconds_until_monthly_reset", return_value=60):
                    with patch.object(web_search.requests, "get") as mock_get:
                        with self.assertRaises(web_search.WebSearchQuotaExceeded) as cm:
                            web_search.search_brave_llm_context("example query")

        self.assertEqual(cm.exception.limit, 500)
        self.assertEqual(cm.exception.retry_after_seconds, 60)
        mock_get.assert_not_called()

    def test_maybe_augment_messages_publishes_search_events_and_adds_context(self):
        messages = [{"role": "user", "content": "今日のPythonニュースを調べて"}]
        events = []
        result = web_search.WebSearchResult(
            query="Python news",
            searched_at="2026-04-30T00:00:00+00:00",
            sources=(
                web_search.WebSearchSource(
                    url="https://example.com/python",
                    title="Python News",
                    hostname="example.com",
                    age="2026-04-30",
                    snippets=("Python released news.",),
                ),
            ),
        )

        with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}, clear=False):
            with patch.object(
                web_search,
                "decide_web_search",
                return_value=web_search.WebSearchDecision(True, "Python news", "pd", "current"),
            ):
                with patch.object(web_search, "search_brave_llm_context", return_value=result):
                    augmented = web_search.maybe_augment_messages_with_web_search(
                        messages,
                        "gemini-2.5-flash",
                        publish_event=lambda event, payload: events.append(
                            SimpleNamespace(event=event, payload=payload)
                        ),
                    )

        self.assertEqual([event.event for event in events], ["web_search_started", "web_search_completed"])
        self.assertEqual(events[1].payload["source_count"], 1)
        self.assertEqual(len(augmented), 2)
        self.assertIn("<web_search_context", augmented[0]["content"])
        self.assertIn("すでにBraveによるリアルタイムWeb検索を実行済み", augmented[0]["content"])
        self.assertIn("リアルタイム検索できない」とは言わないでください", augmented[0]["content"])
        self.assertIn("https://example.com/python", augmented[0]["content"])

    def test_maybe_augment_messages_reports_monthly_quota_exceeded(self):
        messages = [{"role": "user", "content": "今日のPythonニュースを調べて"}]
        events = []

        with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}, clear=False):
            with patch.object(
                web_search,
                "decide_web_search",
                return_value=web_search.WebSearchDecision(True, "Python news", "pd", "current"),
            ):
                with patch.object(
                    web_search,
                    "search_brave_llm_context",
                    side_effect=web_search.WebSearchQuotaExceeded(500, 60),
                ):
                    augmented = web_search.maybe_augment_messages_with_web_search(
                        messages,
                        "gemini-2.5-flash",
                        publish_event=lambda event, payload: events.append(
                            SimpleNamespace(event=event, payload=payload)
                        ),
                    )

        self.assertEqual([event.event for event in events], ["web_search_started", "web_search_failed"])
        self.assertIn("月間上限", events[1].payload["message"])
        self.assertIn("月間上限", augmented[0]["content"])
        self.assertIn("リアルタイム確認ができない", augmented[0]["content"])


if __name__ == "__main__":
    unittest.main()
