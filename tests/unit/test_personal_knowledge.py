"""チャットのメモ検索（personal_knowledge_search）が、メモだけを対象にすること（記憶は読まない）、失敗の記録、ツール呼び出しの契約、
メモ由来の結果では「常に承認」の自動実行を止めないことを検証するテスト（ADR 0025）。

Tests chat memo search (personal_knowledge_search): it reads memos only and never memory, records failures, keeps the tool call
contract, and never stops auto-run under "always approve" on account of memos (ADR 0025).
"""

import json
import unittest
from unittest.mock import AsyncMock, patch

from services.chat_agent_budget import AgentStepBudget
from services.chat_evidence_store import EvidenceStore
from services.chat_generation import ChatGenerationJob
from services.personal_knowledge import (
    PERSONAL_KNOWLEDGE_TOOL_NAME,
    PersonalKnowledgeResult,
    build_personal_knowledge_tool_payload,
    build_personal_overview,
    get_personal_knowledge_tool_definition,
    search_personal_knowledge,
    search_personal_knowledge_for_tool,
)
from services.research_state import TurnState
from services.selected_reference_context import (
    PERSONAL_KNOWLEDGE_SOURCE,
    SelectedReferenceLookupTrace,
)


# メモ検索の 1 件分の代役。
# Stand-in for one memo search hit.
class _Memo:
    def __init__(self, memo_id=1, title="沖縄旅行", excerpt="予算"):
        self.id = memo_id
        self.title = title
        self.excerpt = excerpt
        self.updated_at = "2026-08-01T00:00:00"
        self.collection_name = None


# メモ詳細の代役。本文だけを持つ。
# Stand-in for memo detail; it only carries the body.
class _MemoDetail:
    content = "本文全体"


# メモ検索結果の代役。
# Stand-in for a memo search result.
class _MemoSearch:
    def __init__(self, memos):
        self.memos = memos


# 検索・概観の非同期サービスをモックし、メモだけを読むこととフォールバックを確かめる。
# Mocks the async search and overview services and checks that only memos are read, and the fallbacks.
class PersonalKnowledgeSearchTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_reads_memos_only_and_never_touches_memory(self):
        # 記憶の検索関数（旧 search_facts・記憶の検索）が、モジュールに残っていても呼ばれない。
        # No memory lookup is reachable from here: the module no longer even imports one.
        import services.personal_knowledge as module

        self.assertFalse(hasattr(module, "search_facts"))
        self.assertFalse(hasattr(module, "build_digest"))
        with patch(
            "services.personal_knowledge.search_memos",
            new=AsyncMock(return_value=_MemoSearch([_Memo()])),
        ), patch(
            "services.personal_knowledge.get_memo",
            new=AsyncMock(return_value=_MemoDetail()),
        ), patch("services.context_vault_service.search_facts", new=AsyncMock()) as facts, patch(
            "services.memory_search.search_facts_ranked", new=AsyncMock()
        ) as ranked:
            result = await search_personal_knowledge(7, " 沖縄 ")
            payload = await search_personal_knowledge_for_tool(7, "沖縄")

        self.assertEqual(result.query, "沖縄")
        self.assertEqual(result.memos[0]["content"], "本文全体")
        self.assertFalse(hasattr(result, "facts"))
        self.assertNotIn("context_facts", payload)
        self.assertNotIn("context_fact_count", payload)
        facts.assert_not_awaited()
        ranked.assert_not_awaited()

    async def test_semantic_memo_miss_falls_back_to_keyword(self):
        modes = []

        async def search(_user_id, _query, *, mode, limit, **_kwargs):
            del limit
            modes.append(mode)
            return _MemoSearch([] if mode == "semantic" else [_Memo(4)])

        with patch("services.personal_knowledge.search_memos", new=search), patch(
            "services.personal_knowledge.get_memo", new=AsyncMock(return_value=_MemoDetail())
        ):
            result = await search_personal_knowledge(7, "沖縄")
        self.assertEqual(modes, ["semantic", "keyword"])
        self.assertEqual(result.memos[0]["id"], 4)

    async def test_a_failed_memo_search_is_a_failure_not_a_zero_hit(self):
        with patch(
            "services.personal_knowledge.search_memos",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ):
            result = await search_personal_knowledge(7, "口調")
        self.assertTrue(result.failed)
        self.assertFalse(result.has_hits)

    async def test_blank_query_skips_async_database_services(self):
        memo_search = AsyncMock()
        with patch("services.personal_knowledge.search_memos", new=memo_search):
            result = await search_personal_knowledge(7, " ")
        memo_search.assert_not_awaited()
        self.assertFalse(result.has_hits)

    async def test_overview_lists_recent_memo_titles_only(self):
        listing = type("Listing", (), {"memos": [_Memo(3, "8月の目標")]})()
        with patch(
            "services.personal_knowledge.list_memos",
            new=AsyncMock(return_value=listing),
        ) as list_call, patch("services.context_vault_service.build_digest", new=AsyncMock()) as digest:
            overview = await build_personal_overview(7)
        self.assertEqual(list_call.await_args.kwargs["sort"], "updated")
        self.assertEqual(overview, {"recent_memos": overview["recent_memos"], "recent_memo_count": 1})
        self.assertEqual(overview["recent_memos"][0]["title"], "8月の目標")
        digest.assert_not_awaited()

    async def test_an_overview_that_cannot_list_memos_is_empty_not_an_error(self):
        with patch("services.personal_knowledge.list_memos", new=AsyncMock(side_effect=RuntimeError("db down"))):
            overview = await build_personal_overview(7)

        self.assertEqual(overview, {"recent_memos": [], "recent_memo_count": 0})


# 失敗と結果なしが、ペイロード上で区別できることを確かめる。
# Checks failed and empty results are distinguishable in the payload.
class PersonalKnowledgePayloadTestCase(unittest.TestCase):
    def test_failed_and_empty_payloads_are_distinct(self):
        failed = build_personal_knowledge_tool_payload(PersonalKnowledgeResult(query="沖縄", failed=True))
        empty = build_personal_knowledge_tool_payload(PersonalKnowledgeResult(query="沖縄"))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(empty["status"], "no_results")

    def test_the_wording_names_memos_only(self):
        # LLM に渡る文面（ツールの説明・結果の注記）に、記憶や旧称（My Context）が残っていない。
        # Nothing the LLM reads (tool description, result notes) mentions memory or the old name (My Context).
        definition = get_personal_knowledge_tool_definition()
        payloads = [
            build_personal_knowledge_tool_payload(PersonalKnowledgeResult(query="q", failed=True)),
            build_personal_knowledge_tool_payload(PersonalKnowledgeResult(query="q")),
            build_personal_knowledge_tool_payload(PersonalKnowledgeResult(query="q", memos=[{"title": "m"}])),
        ]

        for text in (json.dumps(definition, ensure_ascii=False), *(json.dumps(p, ensure_ascii=False) for p in payloads)):
            for forbidden in ("My Context", "context fact", "memory", "Memory", "記憶", "preferences, profile"):
                self.assertNotIn(forbidden, text)
        self.assertIn("memos", definition["function"]["description"])
        self.assertEqual(definition["function"]["name"], PERSONAL_KNOWLEDGE_TOOL_NAME)
        self.assertEqual(PERSONAL_KNOWLEDGE_TOOL_NAME, "personal_knowledge_search")


# ツール呼び出しが生成の契約（予算・台帳・証拠・信頼度）を保つことを確かめる。
# Checks the tool call keeps the generation contract (budget, ledger, evidence and trust level).
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
                "memos": [],
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
            result_counts=("memo_count",),
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

    def test_a_memo_result_never_stops_auto_approval_on_account_of_memory(self):
        # メモは本人のデータ。以前は結果に未確認の記憶が含まれると止めていたが、この経路はもう記憶を返さない。
        # 古い形（未確認の事実を含む結果）が来ても、メモの経路は止めない。
        # Memos are the owner's data. This path used to stop on an unconfirmed fact in its result; it no longer returns memory, and even
        # an old-shaped result carrying one does not stop it here.
        for payload in (
            {"status": "ok", "memo_count": 1, "memos": [{"id": 1, "title": "m"}]},
            {"status": "ok", "memo_count": 0, "memos": [], "context_facts": [{"source_kind": "mcp", "confirmed": False}]},
        ):
            with self.subTest(payload=payload):
                job = ChatGenerationJob(
                    conversation_messages=[{"role": "user", "content": "この情報でTaskを作って"}],
                    model="test-model",
                    persist_response=lambda response, **kwargs: None,
                    personal_knowledge_search=lambda _query, payload=payload: payload,
                )
                state = job._build_turn_run_state()
                tool_call = {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": PERSONAL_KNOWLEDGE_TOOL_NAME, "arguments": json.dumps({"query": "Taskの情報"})},
                }

                job._configure_agent_tools(state)
                job._dispatch_tool_calls(state, [tool_call], llm_step=1)

                self.assertFalse(state.untrusted_input_ingested)

    def test_selected_memo_results_and_overviews_never_stop_auto_approval_on_account_of_memory(self):
        for status in ("ok", "overview"):
            with self.subTest(status=status):
                job = ChatGenerationJob(
                    conversation_messages=[{"role": "user", "content": "メモを使う"}],
                    model="test-model",
                    persist_response=lambda response, **kwargs: None,
                    selected_reference_trace=[
                        SelectedReferenceLookupTrace(
                            source=PERSONAL_KNOWLEDGE_SOURCE,
                            query="勤務先",
                            payload={
                                "status": status,
                                "memos": [{"id": 1, "title": "m"}],
                                "context_facts": [{"source_kind": "mcp", "confirmed": False}],
                            },
                        )
                    ],
                )

                state = job._build_turn_run_state()

                self.assertFalse(state.untrusted_input_ingested)


if __name__ == "__main__":
    unittest.main()
