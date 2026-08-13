import json
import unittest
from unittest.mock import patch

from services.chat_generation import ChatGenerationJob
from services.personal_knowledge import (
    PERSONAL_KNOWLEDGE_TOOL_NAME,
    PersonalKnowledgeResult,
    build_personal_knowledge_tool_payload,
    search_personal_knowledge,
)


# 日本語: mcp_memo_service の検索結果を模した最小オブジェクト。
# English: Minimal stand-in for a memo search hit returned by mcp_memo_service.
class _FakeMemo:
    def __init__(self, memo_id, title, excerpt):
        self.id = memo_id
        self.title = title
        self.excerpt = excerpt
        self.updated_at = "2026-08-01T00:00:00"
        self.collection_name = None


class _FakeMemoDetail:
    def __init__(self, content):
        self.content = content


class _FakeMemoSearchResult:
    def __init__(self, memos):
        self.memos = memos


class _FakeFact:
    def __init__(self, fact_id, title, content):
        self.id = fact_id
        self.fact_type = "preference"
        self.title = title
        self.content = content
        self.importance = 70
        self.updated_at = "2026-08-02T00:00:00"


class _FakeFactSearchResult:
    def __init__(self, facts):
        self.facts = facts


class PersonalKnowledgeSearchTestCase(unittest.TestCase):
    # 日本語: メモとマイコンテキストの両方を1つの検索結果へまとめることを確認します。
    # English: Both memos and My Context facts must land in a single result.
    def test_merges_memo_and_context_hits(self):
        memos = _FakeMemoSearchResult([_FakeMemo(1, "沖縄旅行", "予算は10万円")])
        facts = _FakeFactSearchResult([_FakeFact(9, "移動手段", "飛行機が好み")])

        with patch("services.personal_knowledge.search_memos", return_value=memos), patch(
            "services.personal_knowledge.get_memo", return_value=_FakeMemoDetail("本文全体")
        ), patch("services.personal_knowledge.search_facts", return_value=facts):
            result = search_personal_knowledge(7, " 沖縄 ")

        self.assertEqual(result.query, "沖縄")
        self.assertEqual([memo["title"] for memo in result.memos], ["沖縄旅行"])
        # 上位のヒットは抜粋だけでなく全文も渡す。
        # Top hits carry the full body, not just the excerpt.
        self.assertEqual(result.memos[0]["content"], "本文全体")
        self.assertEqual([fact["title"] for fact in result.facts], ["移動手段"])

    # 日本語: 片方の検索が落ちても、もう片方の結果で回答できるようにします。
    # English: One failing source must not discard the other source's hits.
    def test_returns_context_hits_when_memo_search_fails(self):
        facts = _FakeFactSearchResult([_FakeFact(3, "口調", "結論から簡潔に")])

        with patch("services.personal_knowledge.search_memos", side_effect=RuntimeError("db down")), patch(
            "services.personal_knowledge.search_facts", return_value=facts
        ):
            result = search_personal_knowledge(7, "口調")

        self.assertEqual(result.memos, [])
        self.assertEqual([fact["title"] for fact in result.facts], ["口調"])

    # 日本語: 空クエリでは検索そのものを行いません。
    # English: An empty query performs no lookup at all.
    def test_blank_query_skips_the_lookup(self):
        with patch("services.personal_knowledge.search_memos") as memo_search, patch(
            "services.personal_knowledge.search_facts"
        ) as fact_search:
            result = search_personal_knowledge(7, "   ")

        memo_search.assert_not_called()
        fact_search.assert_not_called()
        self.assertFalse(result.has_hits)

    # 日本語: ヒット0件は「無かった」と明示し、捏造させないためのメッセージを返します。
    # English: Zero hits must be reported explicitly so the model does not invent a memo.
    def test_empty_payload_tells_the_model_nothing_matched(self):
        payload = build_personal_knowledge_tool_payload(PersonalKnowledgeResult(query="沖縄"))

        self.assertEqual(payload["status"], "no_results")
        self.assertEqual(payload["memos"], [])
        self.assertEqual(payload["context_facts"], [])


class PersonalKnowledgeToolCallTestCase(unittest.TestCase):
    def _build_job(self, search):
        events = []
        job = ChatGenerationJob(
            conversation_messages=[{"role": "user", "content": "去年の沖縄旅行の予算は？"}],
            model="test-model",
            persist_response=lambda response, **kwargs: None,
            on_event=lambda event: events.append((event.event, event.payload)),
            personal_knowledge_search=search,
        )
        return job, events

    @staticmethod
    def _run(job, tool_call, *, current_messages, step_count, max_steps):
        return job._run_lookup_tool_call(
            tool_call,
            tool_name=PERSONAL_KNOWLEDGE_TOOL_NAME,
            search=job._personal_knowledge_search,
            event_prefix="personal_knowledge_search",
            result_counts=("memo_count", "context_fact_count"),
            failure_log_message="Memo / context search via tool call failed.",
            failure_tool_message="Memo and My Context search failed.",
            current_messages=current_messages,
            step_count=step_count,
            max_steps=max_steps,
        )

    @staticmethod
    def _tool_call(arguments):
        return {
            "id": "call_1",
            "type": "function",
            "function": {"name": PERSONAL_KNOWLEDGE_TOOL_NAME, "arguments": json.dumps(arguments)},
        }

    # 日本語: 検索結果はツール結果メッセージとして会話へ戻り、進捗イベントも発行されます。
    # English: Results return as a tool message and the step publishes progress events.
    def test_tool_call_appends_results_and_publishes_steps(self):
        payload = {"status": "ok", "memo_count": 2, "context_fact_count": 1, "memos": [], "context_facts": []}
        job, events = self._build_job(lambda query: payload)
        messages = []

        next_step = self._run(
            job,
            self._tool_call({"query": "沖縄 予算"}),
            current_messages=messages,
            step_count=1,
            max_steps=8,
        )

        self.assertEqual(next_step, 2)
        self.assertEqual(messages[0]["role"], "tool")
        self.assertEqual(json.loads(messages[0]["content"])["memo_count"], 2)
        self.assertEqual(
            [name for name, _ in events],
            ["personal_knowledge_search_started", "personal_knowledge_search_completed"],
        )
        self.assertEqual(events[1][1]["memo_count"], 2)

    # 日本語: 空クエリはステップを消費せず、引数エラーとして戻します。
    # English: A blank query costs no step and comes back as an argument error.
    def test_blank_query_does_not_consume_a_step(self):
        job, events = self._build_job(lambda query: {"status": "ok"})
        messages = []

        next_step = self._run(
            job,
            self._tool_call({"query": "  "}),
            current_messages=messages,
            step_count=1,
            max_steps=8,
        )

        self.assertEqual(next_step, 1)
        self.assertEqual(json.loads(messages[0]["content"])["status"], "invalid_arguments")
        self.assertEqual(events, [])

    # 日本語: 残りステップが無いときは検索せず、既存情報で回答するよう促します。
    # English: With no steps left the lookup is skipped and the model is told to answer as-is.
    def test_step_limit_skips_the_lookup(self):
        calls = []
        job, _events = self._build_job(lambda query: calls.append(query) or {"status": "ok"})
        messages = []

        next_step = self._run(
            job,
            self._tool_call({"query": "沖縄"}),
            current_messages=messages,
            step_count=8,
            max_steps=8,
        )

        self.assertEqual(next_step, 8)
        self.assertEqual(calls, [])
        self.assertEqual(json.loads(messages[0]["content"])["status"], "step_limit_reached")

    # 日本語: 検索が例外を投げても生成は続き、失敗をイベントとツール結果で伝えます。
    # English: A failing lookup keeps generation alive and reports the failure both ways.
    def test_failed_lookup_reports_and_continues(self):
        def _raise(query):
            raise RuntimeError("search exploded")

        job, events = self._build_job(_raise)
        messages = []

        next_step = self._run(
            job,
            self._tool_call({"query": "沖縄"}),
            current_messages=messages,
            step_count=1,
            max_steps=8,
        )

        self.assertEqual(next_step, 2)
        self.assertEqual(json.loads(messages[0]["content"])["status"], "failed")
        self.assertEqual(
            [name for name, _ in events],
            ["personal_knowledge_search_started", "personal_knowledge_search_failed"],
        )


if __name__ == "__main__":
    unittest.main()
