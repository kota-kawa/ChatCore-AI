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

    def test_decide_web_search_falls_back_for_explicit_search_request(self):
        messages = [{"role": "user", "content": "React 19の最新情報を検索して"}]

        with patch.object(web_search, "get_llm_response", side_effect=RuntimeError("down")):
            decision = web_search.decide_web_search(messages, "gemini-2.5-flash")

        self.assertTrue(decision.should_search)
        self.assertIn("React 19", decision.query)

    def test_decide_web_search_skips_planner_for_plain_greeting(self):
        messages = [{"role": "user", "content": "こんにちは"}]

        with patch.object(web_search, "get_llm_response") as mock_llm:
            decision = web_search.decide_web_search(messages, "gemini-2.5-flash")

        self.assertFalse(decision.should_search)
        mock_llm.assert_not_called()

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
        self.assertIn("monthly quota is exhausted", augmented[0]["content"])


if __name__ == "__main__":
    unittest.main()
