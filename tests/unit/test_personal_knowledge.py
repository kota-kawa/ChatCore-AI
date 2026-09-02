import json
import unittest
from unittest.mock import AsyncMock, patch

from services.chat_agent_budget import AgentStepBudget
from services.chat_evidence_store import EvidenceStore
from services.chat_generation import ChatGenerationJob
from services.research_state import TurnState
from services.personal_knowledge import (
    PERSONAL_KNOWLEDGE_TOOL_NAME,
    PersonalKnowledgeResult,
    build_personal_knowledge_tool_payload,
    build_personal_overview,
    search_personal_knowledge,
)


class _Memo:
    def __init__(self, memo_id=1, title="沖縄旅行", excerpt="予算"):
        self.id = memo_id
        self.title = title
        self.excerpt = excerpt
        self.updated_at = "2026-08-01T00:00:00"
        self.collection_name = None


class _MemoDetail:
    content = "本文全体"


class _MemoSearch:
    def __init__(self, memos):
        self.memos = memos


class _Fact:
    id = 9
    fact_type = "preference"
    title = "移動手段"
    content = "飛行機が好み"
    importance = 70
    updated_at = "2026-08-02T00:00:00"


class _FactSearch:
    facts = [_Fact()]


class PersonalKnowledgeSearchTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_merges_async_memo_and_context_hits(self):
        with patch(
            "services.personal_knowledge.search_memos",
            new=AsyncMock(return_value=_MemoSearch([_Memo()])),
        ), patch(
            "services.personal_knowledge.get_memo",
            new=AsyncMock(return_value=_MemoDetail()),
        ), patch(
            "services.personal_knowledge.search_facts",
            new=AsyncMock(return_value=_FactSearch()),
        ):
            result = await search_personal_knowledge(7, " 沖縄 ")
        self.assertEqual(result.query, "沖縄")
        self.assertEqual(result.memos[0]["content"], "本文全体")
        self.assertEqual(result.facts[0]["title"], "移動手段")

    async def test_semantic_memo_miss_falls_back_to_keyword(self):
        modes = []

        async def search(_user_id, _query, *, mode, limit, **_kwargs):
            del limit
            modes.append(mode)
            return _MemoSearch([] if mode == "semantic" else [_Memo(4)])

        with patch("services.personal_knowledge.search_memos", new=search), patch(
            "services.personal_knowledge.get_memo", new=AsyncMock(return_value=_MemoDetail())
        ), patch(
            "services.personal_knowledge.search_facts",
            new=AsyncMock(return_value=type("Facts", (), {"facts": []})()),
        ):
            result = await search_personal_knowledge(7, "沖縄")
        self.assertEqual(modes, ["semantic", "keyword"])
        self.assertEqual(result.memos[0]["id"], 4)

    async def test_failed_one_side_is_recorded_without_discarding_other_side(self):
        with patch(
            "services.personal_knowledge.search_memos",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ), patch(
            "services.personal_knowledge.search_facts",
            new=AsyncMock(return_value=_FactSearch()),
        ):
            result = await search_personal_knowledge(7, "口調")
        self.assertEqual(result.failed_sources, ("memo",))
        self.assertEqual(result.facts[0]["title"], "移動手段")

    async def test_blank_query_skips_async_database_services(self):
        memo_search = AsyncMock()
        fact_search = AsyncMock()
        with patch("services.personal_knowledge.search_memos", new=memo_search), patch(
            "services.personal_knowledge.search_facts", new=fact_search
        ):
            result = await search_personal_knowledge(7, " ")
        memo_search.assert_not_awaited()
        fact_search.assert_not_awaited()
        self.assertFalse(result.has_hits)

    async def test_overview_awaits_memo_listing_and_context_digest(self):
        listing = type("Listing", (), {"memos": [_Memo(3, "8月の目標")]})()
        fact = _Fact()
        digest = type(
            "Digest",
            (),
            {"groups": [type("Group", (), {"facts": [fact]})()]},
        )()
        with patch(
            "services.personal_knowledge.list_memos",
            new=AsyncMock(return_value=listing),
        ) as list_call, patch(
            "services.personal_knowledge.build_digest",
            new=AsyncMock(return_value=digest),
        ):
            overview = await build_personal_overview(7)
        self.assertEqual(list_call.await_args.kwargs["sort"], "updated")
        self.assertEqual(overview["recent_memo_count"], 1)
        self.assertEqual(overview["context_fact_count"], 1)


class PersonalKnowledgePayloadTestCase(unittest.TestCase):
    def test_failed_and_empty_payloads_are_distinct(self):
        failed = build_personal_knowledge_tool_payload(
            PersonalKnowledgeResult(query="沖縄", failed_sources=("memo",))
        )
        empty = build_personal_knowledge_tool_payload(PersonalKnowledgeResult(query="沖縄"))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(empty["status"], "no_results")


class PersonalKnowledgeToolCallTestCase(unittest.TestCase):
    def test_tool_call_keeps_generation_contract(self):
        events = []
        job = ChatGenerationJob(
            conversation_messages=[{"role": "user", "content": "沖縄旅行"}],
            model="test-model",
            persist_response=lambda response, **kwargs: None,
            on_event=lambda event: events.append(event.event),
            personal_knowledge_search=lambda _query: {
                "status": "ok",
                "memo_count": 1,
                "context_fact_count": 0,
                "memos": [],
                "context_facts": [],
            },
        )
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": PERSONAL_KNOWLEDGE_TOOL_NAME,
                "arguments": json.dumps({"query": "沖縄"}),
            },
        }
        messages = []
        # 推論ターンとツール実行は別カウンタ。ツール実行だけが1増える。
        # Reasoning turns and tool calls use separate counters; only tool calls advance here.
        budget = AgentStepBudget(max_llm_turns=4, max_tool_calls=4, llm_turns=1)
        turn_state = TurnState(objective="沖縄旅行")
        job._run_lookup_tool_call(
            tool_call,
            tool_name=PERSONAL_KNOWLEDGE_TOOL_NAME,
            search=job._personal_knowledge_search,
            event_prefix="personal_knowledge_search",
            result_counts=("memo_count", "context_fact_count"),
            failure_log_message="lookup failed",
            failure_tool_message="lookup failed",
            current_messages=messages,
            budget=budget,
            turn_state=turn_state,
            evidence_store=EvidenceStore(),
        )
        self.assertEqual(budget.tool_calls, 1)
        self.assertEqual(budget.llm_turns, 1)
        self.assertEqual(budget.step, 2)
        self.assertEqual(json.loads(messages[0]["content"])["memo_count"], 1)
        self.assertEqual(
            events,
            ["personal_knowledge_search_started", "personal_knowledge_search_completed"],
        )
        # 参照結果は TurnState の検索台帳と Evidence 参照として残る。
        # The lookup result is recorded in the TurnState ledger and as evidence references.
        self.assertEqual(
            [search.tool_name for search in turn_state.executed_searches],
            [PERSONAL_KNOWLEDGE_TOOL_NAME],
        )
        self.assertEqual(turn_state.executed_searches[0].query, "沖縄")


if __name__ == "__main__":
    unittest.main()
