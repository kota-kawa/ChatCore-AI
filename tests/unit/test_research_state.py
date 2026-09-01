import json
import unittest

from services.research_state import (
    RESEARCH_STATE_MARKER,
    ResearchState,
)
from services.web_search import WebSearchResult, WebSearchSource


class ResearchStateTestCase(unittest.TestCase):
    def _result(self, *, url="https://example.com/a", text="evidence"):
        return WebSearchResult(
            query="query",
            searched_at="2026-09-01T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url=url,
                    title="Source",
                    hostname="example.com",
                    age="2026-09-01",
                    snippets=("short snippet",),
                    page_text=text,
                ),
            ),
        )

    def test_repeated_evidence_is_merged_and_richer_excerpt_wins(self):
        state = ResearchState(user_request="question")
        first = state.add_web_result(self._result(text="short"))
        second = state.add_web_result(self._result(text="a much richer evidence excerpt"))

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(state.evidence_count, 1)
        record = next(iter(state.evidence.values()))
        self.assertEqual(record.excerpt, "a much richer evidence excerpt")
        self.assertEqual(record.occurrences, 2)
        self.assertEqual(record.age, "2026-09-01")
        self.assertEqual(record.searched_at, "2026-09-01T00:00:00+00:00")

    def test_state_keeps_semantic_notes_and_summary_bounded(self):
        state = ResearchState(user_request="question", coverage_requirements=("A",))
        for index in range(10):
            state.add_step_note(f"note {index}")
        state.merge_summary(
            {
                "facts": [f"fact {index}" for index in range(30)],
                "uncertainties": [f"unknown {index}" for index in range(20)],
                "answer_plan": "answer plan",
            }
        )

        self.assertLessEqual(len(state.step_notes), 6)
        self.assertLessEqual(len(state.summary["facts"]), 16)
        self.assertLessEqual(len(state.summary["uncertainties"]), 8)
        self.assertIn("answer plan", state.summary["answer_plan"])

    def test_projection_removes_tool_history_and_preserves_state(self):
        state = ResearchState(user_request="question")
        state.add_web_result(self._result())
        messages = [
            {"role": "system", "content": "base"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call"}]},
            {"role": "tool", "tool_call_id": "call", "content": "large"},
        ]

        projected = state.projected_messages(messages)

        self.assertFalse(any(message.get("role") == "tool" for message in projected))
        self.assertFalse(any(message.get("tool_calls") for message in projected))
        self.assertTrue(any(RESEARCH_STATE_MARKER in message.get("content", "") for message in projected))
        self.assertTrue(any(message.get("role") == "user" for message in projected))

    def test_projection_keeps_standing_prompt_that_mentions_reference_tag(self):
        state = ResearchState(user_request="question")
        messages = [
            {
                "role": "system",
                "content": "When <web_search_context> is present, cite the source.",
            },
            {"role": "user", "content": "question"},
        ]

        projected = state.projected_messages(messages)

        self.assertTrue(
            any(
                message.get("content") == messages[0]["content"]
                for message in projected
            )
        )

    def test_render_preserves_evidence_ids_under_small_budget(self):
        state = ResearchState(user_request="question")
        for index in range(10):
            state.add_web_result(
                self._result(url=f"https://example.com/{index}", text="long evidence " * 100)
            )

        rendered = state.render(max_chars=1_100, max_tokens=1_000)

        self.assertIn(RESEARCH_STATE_MARKER, rendered)
        self.assertIn("evidence_id", rendered)
        self.assertLessEqual(len(rendered), 1_100)
        json_start = rendered.find("{", rendered.find(RESEARCH_STATE_MARKER))
        self.assertGreaterEqual(json_start, 0)
        json_end = rendered.rfind("\n</research_state>")
        payload = json.loads(rendered[json_start:json_end])
        self.assertIsInstance(payload, dict)

    def test_reference_payload_is_projected_with_source_type(self):
        state = ResearchState(user_request="question")
        state.add_reference_payload(
            {
                "status": "ok",
                "prompts": [{"prompt_id": "p1", "title": "Prompt", "content": "body"}],
            },
            source_type="shared_prompt",
        )

        record = next(iter(state.evidence.values()))
        self.assertEqual(record.source_type, "shared_prompt")
        self.assertEqual(record.evidence_id, "shared_prompt:prompts:p1")

    def test_reference_payload_keeps_memos_and_context_facts_from_overview(self):
        state = ResearchState(user_request="question")
        state.add_reference_payload(
            {
                "status": "overview",
                "message": "The overview is reference data, not a search match.",
                "recent_memos": [
                    {"id": 3, "title": "August goals"},
                    {"id": 4, "title": "September goals"},
                ],
                "context_facts": [
                    {"id": 9, "title": "Active project", "content": "Chat-Core"}
                ],
            },
            source_type="personal_knowledge_search",
        )

        self.assertEqual(state.evidence_count, 3)
        self.assertTrue(
            any(record.excerpt == "August goals" for record in state.evidence.values())
        )
        self.assertTrue(
            any(record.excerpt == "Chat-Core" for record in state.evidence.values())
        )
        self.assertIn(
            "The overview is reference data, not a search match.",
            state.status_messages,
        )
        self.assertIn("user_request", state.render())


if __name__ == "__main__":
    unittest.main()
