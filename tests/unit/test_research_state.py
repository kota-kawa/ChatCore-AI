import json
import unittest

from services.research_state import (
    TURN_STATE_MARKER,
    EvidenceReference,
    TurnState,
    TurnStateProjectionError,
)


class TurnStateTestCase(unittest.TestCase):
    def _web_ref(self, evidence_id: str, *, raw_text: str = ""):
        # Unknown metadata from the evidence store is ignored, so raw content cannot enter state.
        return {
            "evidence_id": evidence_id,
            "source_type": "web",
            "title": "Source",
            "url": f"https://example.com/{evidence_id}",
            "storage_key": evidence_id,
            "page_text": raw_text,
            "snippets": [raw_text],
        }

    def test_search_records_only_stable_external_references(self):
        state = TurnState(objective="answer the question")
        execution = state.record_search(
            tool_name="web_search",
            query="query",
            search_id="web-1",
            evidence_refs=[
                self._web_ref("ev-1", raw_text="full raw page must stay external")
            ],
        )

        reference = state.evidence_refs["ev-1"]
        self.assertEqual(execution.evidence_ids, ("ev-1",))
        self.assertEqual(reference.search_ids, ("web-1",))
        self.assertEqual(state.evidence_lookup("ev-1"), (("web-1", "ev-1"),))
        serialized = json.dumps(state.as_dict())
        self.assertNotIn("full raw page must stay external", serialized)

    def test_record_evidence_refs_accepts_store_metadata_and_merges_locations(self):
        state = TurnState(objective="question")
        state.record_evidence_refs(
            [EvidenceReference("ev-1", source_type="web")], search_id="web-1"
        )
        state.record_evidence_refs(
            [self._web_ref("ev-1")], search_id="web-2"
        )

        self.assertEqual(
            state.evidence_lookup("ev-1"),
            (("web-1", "ev-1"), ("web-2", "ev-1")),
        )
        self.assertEqual(state.evidence_refs["ev-1"].source_type, "web")

    def test_model_update_replaces_semantic_state_and_can_drop_references(self):
        state = TurnState(
            objective="original objective",
            unresolved_questions=["old unknown"],
        )
        state.record_search(
            tool_name="web_search",
            query="first",
            search_id="web-1",
            evidence_refs=[self._web_ref("keep")],
        )
        state.record_search(
            tool_name="web_search",
            query="second",
            search_id="web-2",
            evidence_refs=[self._web_ref("drop")],
        )

        state.apply_model_update(
            {
                "objective": "corrected objective",
                "unresolved_questions": ["new unknown"],
                "facts": [
                    {"statement": "corrected fact", "evidence_ids": ["keep", "unknown"]}
                ],
                "evidence_ids": ["keep"],
                "ready_to_answer": False,
            }
        )

        self.assertEqual(state.objective, "corrected objective")
        self.assertEqual(state.unresolved_questions, ["new unknown"])
        self.assertEqual(state.facts[0].statement, "corrected fact")
        self.assertEqual(state.facts[0].evidence_ids, ("keep",))
        self.assertIn("keep", state.evidence_refs)
        self.assertNotIn("drop", state.evidence_refs)
        self.assertEqual(len(state.executed_searches), 2)

        state.apply_model_update(
            {
                "unresolved_questions": [],
                "facts": [{"statement": "revised fact", "evidence_ids": ["keep"]}],
                "ready_to_answer": True,
            }
        )
        self.assertEqual(state.unresolved_questions, [])
        self.assertEqual([fact.statement for fact in state.facts], ["revised fact"])
        self.assertTrue(state.ready_to_answer)

    def test_fact_references_are_retained_even_if_omitted_from_evidence_ids(self):
        state = TurnState(objective="question")
        state.record_evidence_refs(
            [self._web_ref("fact-source"), self._web_ref("unused")]
        )

        state.apply_model_update(
            {
                "facts": [
                    {"statement": "supported", "evidence_ids": ["fact-source"]}
                ],
                "evidence_ids": [],
            }
        )

        self.assertEqual(set(state.evidence_refs), {"fact-source"})

    def test_projection_removes_raw_tool_and_reference_history(self):
        state = TurnState(objective="question", unresolved_questions=["need a source"])
        messages = [
            {"role": "system", "content": "base policy"},
            {"role": "system", "content": "<web_search_context>raw result</web_search_context>"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call"}]},
            {"role": "tool", "tool_call_id": "call", "content": "large raw tool output"},
        ]

        projected = state.projected_messages(messages)

        self.assertFalse(any(message.get("role") == "tool" for message in projected))
        self.assertFalse(any(message.get("tool_calls") for message in projected))
        self.assertFalse(any("raw result" in str(message.get("content")) for message in projected))
        state_message = next(
            message for message in projected if TURN_STATE_MARKER in str(message.get("content"))
        )
        self.assertIn('\"objective\":\"question\"', state_message["content"])
        self.assertEqual(projected[0]["content"], "base policy")

    def test_projection_rejects_lossy_token_budget_instead_of_cutting_state(self):
        state = TurnState(
            objective="question",
            unresolved_questions=["an unresolved issue that must not be clipped"],
        )

        with self.assertRaises(TurnStateProjectionError):
            state.render(max_tokens=1)

        rendered = state.render(max_tokens=1_000)
        self.assertIn("an unresolved issue that must not be clipped", rendered)


if __name__ == "__main__":
    unittest.main()
