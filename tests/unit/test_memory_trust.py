"""記憶の「本人由来」の定義が、SQL の条件・結果の判定・自動実行の止め方で同じであることを検証するテスト（ADR 0025）。

Tests that "originates from the owner" means the same in the SQL condition, the result-side check and the auto-approval gate (ADR 0025).
"""

import json
import unittest

from sqlalchemy import column, create_engine, select, table, text
from sqlalchemy.dialects.postgresql import dialect

from services.chat_generation import ChatGenerationJob
from services.chat_tool_calls import _contains_non_owner_unconfirmed_memories
from services.memory_trust import (
    OWNER_EXTRACTED_SOURCE_KIND,
    contains_non_owner_unconfirmed_memory,
    is_owner_originated,
    owner_originated_condition,
)

_SOURCE_KINDS = ("manual", "chat", "mcp", "import")


def _memory(source_kind, confirmed):
    return {"source_kind": source_kind, "confirmed": confirmed}


class OwnerOriginatedDefinitionTestCase(unittest.TestCase):
    def test_confirmed_or_extracted_from_chat_is_the_owners(self):
        expected = {
            ("manual", True): True,
            ("chat", True): True,
            ("chat", False): True,
            ("mcp", True): True,
            ("import", True): True,
            ("mcp", False): False,
            ("import", False): False,
            # 本人が書いた記憶は作成時に確認済みになるが、定義は出所ではなく確認の有無で見る。
            # A manual memory is confirmed at creation, but the definition looks at confirmation, not at who typed it.
            ("manual", False): False,
        }
        for (kind, confirmed), owner in expected.items():
            with self.subTest(source_kind=kind, confirmed=confirmed):
                self.assertEqual(is_owner_originated(confirmed=confirmed, source_kind=kind), owner)

    def test_the_sql_condition_selects_exactly_what_the_python_definition_accepts(self):
        # 同じ定義を実際に評価して突き合わせる（全組み合わせ）。
        # Evaluate the SQL condition for real and compare it with the Python definition over every combination.
        facts = table("facts", column("id"), column("last_confirmed_at"), column("source_kind"))
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        combinations = [(kind, confirmed) for kind in _SOURCE_KINDS for confirmed in (True, False)]
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE facts (id INTEGER, last_confirmed_at TEXT, source_kind TEXT)"))
            for index, (kind, confirmed) in enumerate(combinations):
                connection.execute(
                    text("INSERT INTO facts VALUES (:id, :confirmed, :kind)"),
                    {"id": index, "confirmed": "2026-11-01" if confirmed else None, "kind": kind},
                )
            selected = {
                row[0]
                for row in connection.execute(
                    select(facts.c.id).where(owner_originated_condition(facts.c.last_confirmed_at, facts.c.source_kind))
                )
            }

        self.assertEqual(
            selected,
            {index for index, (kind, confirmed) in enumerate(combinations) if is_owner_originated(confirmed=confirmed, source_kind=kind)},
        )

    def test_the_sql_text_keeps_the_shape_the_memory_summary_query_is_checked_against(self):
        facts = table("context_facts", column("last_confirmed_at"), column("source_kind"))
        sql = str(owner_originated_condition(facts.c.last_confirmed_at, facts.c.source_kind).compile(dialect=dialect()))

        self.assertEqual(
            " ".join(sql.split()),
            "context_facts.last_confirmed_at IS NOT NULL OR context_facts.source_kind = %(source_kind_1)s",
        )
        self.assertEqual(OWNER_EXTRACTED_SOURCE_KIND, "chat")


class ResultCheckTestCase(unittest.TestCase):
    def test_only_unconfirmed_memory_that_is_not_the_owners_counts(self):
        self.assertFalse(contains_non_owner_unconfirmed_memory([_memory("manual", True)]))
        self.assertFalse(contains_non_owner_unconfirmed_memory([_memory("chat", False)]))
        self.assertFalse(contains_non_owner_unconfirmed_memory([_memory("chat", True), _memory("mcp", True)]))
        self.assertTrue(contains_non_owner_unconfirmed_memory([_memory("mcp", False)]))
        self.assertTrue(contains_non_owner_unconfirmed_memory([_memory("import", False)]))

    def test_one_such_memory_among_trusted_ones_is_enough(self):
        self.assertTrue(
            contains_non_owner_unconfirmed_memory([_memory("manual", True), _memory("chat", False), _memory("mcp", False)])
        )

    def test_an_empty_or_missing_list_is_not_a_reason_to_stop(self):
        for value in ([], None, "x", 3, {}):
            with self.subTest(value=value):
                self.assertFalse(contains_non_owner_unconfirmed_memory(value))

    def test_an_item_of_the_wrong_shape_counts_as_unconfirmed(self):
        self.assertTrue(contains_non_owner_unconfirmed_memory(["x"]))
        self.assertTrue(contains_non_owner_unconfirmed_memory([{"source_kind": "mcp"}]))
        # confirmed が True という値そのものだけを確認済みとみなす（"true" や 1 は確認済みではない）。
        # Only the value True counts as confirmed ("true" or 1 do not).
        self.assertTrue(contains_non_owner_unconfirmed_memory([{"source_kind": "mcp", "confirmed": "true"}]))
        self.assertTrue(contains_non_owner_unconfirmed_memory([{"source_kind": "mcp", "confirmed": 1}]))

    def test_the_tool_call_helper_reads_the_named_group(self):
        payload = {"memories": [_memory("mcp", False)], "context_facts": []}

        self.assertTrue(_contains_non_owner_unconfirmed_memories(payload, "memories"))
        self.assertFalse(_contains_non_owner_unconfirmed_memories(payload, "context_facts"))
        self.assertFalse(_contains_non_owner_unconfirmed_memories(None, "memories"))
        self.assertFalse(_contains_non_owner_unconfirmed_memories({}, "memories"))


class AutoApprovalGateTestCase(unittest.TestCase):
    def _dispatch(self, memories):
        job = ChatGenerationJob(
            conversation_messages=[{"role": "user", "content": "この情報でTaskを作って"}],
            model="test-model",
            persist_response=lambda response, **kwargs: None,
            personal_knowledge_search=lambda _query: {
                "status": "ok",
                "memo_count": 0,
                "context_fact_count": len(memories),
                "memos": [],
                "context_facts": memories,
            },
        )
        state = job._build_turn_run_state()
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "personal_knowledge_search", "arguments": json.dumps({"query": "Taskの情報"})},
        }
        job._configure_agent_tools(state)
        job._dispatch_tool_calls(state, [tool_call], llm_step=1)
        return state

    def test_owner_originated_results_do_not_stop_auto_approval(self):
        for memories in ([_memory("manual", True)], [_memory("chat", False)], [_memory("chat", True), _memory("mcp", True)]):
            with self.subTest(memories=memories):
                self.assertFalse(self._dispatch(memories).untrusted_input_ingested)

    def test_a_single_unconfirmed_mcp_or_import_memory_stops_it(self):
        for memories in ([_memory("mcp", False)], [_memory("chat", False), _memory("import", False)]):
            with self.subTest(memories=memories):
                self.assertTrue(self._dispatch(memories).untrusted_input_ingested)


if __name__ == "__main__":
    unittest.main()
