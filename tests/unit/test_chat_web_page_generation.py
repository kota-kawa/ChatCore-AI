"""Known web sources can be read across turns without another search."""

import json
import unittest
from unittest.mock import Mock, patch

from services.chat_agent_budget import AgentStepBudget
from services.chat_generation import ChatGenerationJob
from services.url_fetcher import FetchedUrlDocument
from services.web_search import WebSearchResult, WebSearchSource


def tool_call(name, **arguments):
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def result():
    return WebSearchResult(
        query="previous query",
        searched_at="2026-09-01T00:00:00Z",
        sources=tuple(
            WebSearchSource(
                url=f"https://example.com/{index}", title=f"Article {index}",
                hostname="example.com", age="", snippets=(f"Snippet {index}",),
                page_text="Legacy saved body",  # Old records remain compatible.
            ) for index in range(1, 4)
        ),
    )


class WebPageGenerationTestCase(unittest.TestCase):
    def make_job(self, *, prior=None):
        saved = Mock(return_value=None)
        job = ChatGenerationJob(
            conversation_messages=[{"role": "user", "content": "前の検索の3番目の例外条件を詳しく"}],
            model="openai/gpt-oss-120b", persist_response=saved,
            prior_web_search_results=prior,
        )
        return job, saved

    def test_prior_snippet_then_page_detail_without_search_and_with_citation(self):
        prior = result()
        source = prior.sources[2]
        calls = []
        document = FetchedUrlDocument(source.url, source.url, source.title, "Exception: only administrators may proceed.")

        def stream(messages, _model, *, tools=None, **_kwargs):
            calls.append(messages)
            names = {tool["function"]["name"] for tool in tools or []}
            self.assertNotIn("web_search", names)
            self.assertIn("read_web_page", names)
            if len(calls) == 1:
                system = "\n".join(str(message.get("content")) for message in messages if message["role"] == "system")
                self.assertIn("previous query", system)
                self.assertIn("2026-09-01", system)
                self.assertNotIn("Legacy saved body", system)
                yield json.dumps([tool_call("get_evidence", evidence_ids=[source.evidence_id])])
            elif len(calls) == 2:
                payload = json.loads(messages[-1]["content"])
                self.assertEqual(payload["evidence"][0]["source"]["snippets"], ["Snippet 3"])
                self.assertNotIn("page_text", payload["evidence"][0]["source"])
                yield json.dumps([tool_call("read_web_page", evidence_id=source.evidence_id)])
            else:
                payload = json.loads(messages[-1]["content"])
                self.assertIn("only administrators", payload["text"])
                self.assertEqual(payload["evidence_id"], source.evidence_id)
                yield f"管理者だけが実行できます。[[source:{source.evidence_id}]]"

        job, saved = self.make_job(prior=[prior])
        with (
            patch("services.chat_generation.is_web_search_enabled", return_value=False),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream),
            patch("services.chat_generation.search_brave_llm_context") as search,
            patch("services.chat_web_page_reader.fetch_url_document", return_value=document) as fetch,
        ):
            job._run()
        self.assertEqual(len(calls), 3)
        search.assert_not_called()
        fetch.assert_called_once_with(source.url)
        saved.assert_called_once()
        self.assertIn(f'href="{source.url}"', saved.call_args.args[0])
        self.assertNotIn("[[source:", saved.call_args.args[0])
        self.assertNotIn("web_search_context", saved.call_args.kwargs)
        self.assertEqual(job._telemetry.web_search_count, 0)
        self.assertEqual(job._telemetry.evidence_read_count, 2)

    def test_snippet_sufficient_followup_never_fetches_page(self):
        prior = result()
        calls = 0

        def stream(_messages, _model, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                yield json.dumps([tool_call("get_evidence", evidence_ids=[prior.sources[0].evidence_id])])
            else:
                yield f"Snippet 1です。[[source:{prior.sources[0].evidence_id}]]"

        job, saved = self.make_job(prior=[prior])
        with (
            patch("services.chat_generation.is_web_search_enabled", return_value=False),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream),
            patch("services.chat_web_page_reader.fetch_url_document") as fetch,
            patch("services.chat_generation.search_brave_llm_context") as search,
        ):
            job._run()
        fetch.assert_not_called()
        search.assert_not_called()
        saved.assert_called_once()

    def test_search_limit_still_allows_paged_read_and_persists_only_snippets(self):
        found = result()
        source = found.sources[2]
        calls = 0
        next_start = None
        document = FetchedUrlDocument(source.url, source.url, source.title, "first part\nsecond part")

        def stream(messages, _model, *, tools=None, **_kwargs):
            nonlocal calls, next_start
            calls += 1
            names = {tool["function"]["name"] for tool in tools or []}
            if calls == 1:
                yield json.dumps([tool_call("web_search", query="find articles")])
            elif calls == 2:
                self.assertNotIn("web_search", names)
                self.assertIn("read_web_page", names)
                yield json.dumps([tool_call("read_web_page", evidence_id=source.evidence_id, length=10)])
            elif calls == 3:
                payload = json.loads(messages[-1]["content"])
                self.assertEqual(payload["text"], "first part")
                next_start = payload["next_start"]
                yield json.dumps([tool_call("read_web_page", evidence_id=source.evidence_id, start=next_start)])
            else:
                self.assertIsNone(tools)
                yield f"詳しい回答です。[[source:{source.evidence_id}]]"

        job, saved = self.make_job()
        budget = AgentStepBudget(3, 1, max_read_calls=2)
        with (
            patch("services.chat_generation.AgentStepBudget.from_environment", return_value=budget),
            patch("services.chat_generation.is_web_search_enabled", return_value=True),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream),
            patch("services.chat_generation.search_brave_llm_context", return_value=found) as search,
            patch("services.chat_generation.choose_web_search_images", return_value=[]),
            patch("services.chat_web_page_reader.fetch_url_document", return_value=document) as fetch,
        ):
            job._run()
        self.assertEqual(calls, 4)
        self.assertEqual(next_start, 10)
        fetch.assert_called_once()
        search.assert_called_once()
        self.assertEqual(budget.tool_calls, 1)
        self.assertEqual(budget.read_calls, 2)
        saved.assert_called_once()
        stored_sources = saved.call_args.kwargs["web_search_context"][0]["sources"]
        self.assertEqual([s["url"] for s in stored_sources], [s.url for s in found.sources])
        for stored in stored_sources:
            self.assertNotIn("page_text", stored)
            self.assertNotIn("image_candidates", stored)

    def test_read_limit_does_not_spend_search_budget_and_search_order_is_retained(self):
        prior = result()
        job, _ = self.make_job(prior=[prior])
        state = job._build_turn_run_state()
        state.budget = AgentStepBudget(3, 2, max_read_calls=1)
        with patch("services.chat_generation.is_web_search_enabled", return_value=True):
            job._configure_agent_tools(state)
        job._dispatch_tool_calls(state, [tool_call("get_evidence", evidence_ids=[prior.sources[0].evidence_id])], 1)
        names = {tool["function"]["name"] for tool in job._available_agent_tools(state)}
        self.assertEqual(names, {"web_search"})
        self.assertEqual(state.budget.tool_calls, 0)
        self.assertEqual(state.evidence_context_budget.consumed, 0)
        self.assertGreater(state.budget.read_chars, 0)
        self.assertEqual(state.turn_state.executed_searches[0].evidence_ids, tuple(s.evidence_id for s in prior.sources))
        self.assertEqual(state.turn_state.executed_searches[0].status, "prior_turn")

    def test_read_character_limit_withdraws_reads_without_spending_search_budget(self):
        job, _ = self.make_job(prior=[result()])
        state = job._build_turn_run_state()
        state.budget = AgentStepBudget(3, 2, max_read_chars=500)
        with patch("services.chat_generation.is_web_search_enabled", return_value=True):
            job._configure_agent_tools(state)
        names = {tool["function"]["name"] for tool in job._available_agent_tools(state)}
        self.assertEqual(names, {"web_search"})


if __name__ == "__main__":
    unittest.main()
