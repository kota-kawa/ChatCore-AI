import json
import os
import unittest
from unittest.mock import patch

from services.chat_generation import start_generation_job
from services.llm import LlmInputLimitError
from services.selected_reference_context import SelectedReferenceLookupTrace
from services.web_search import WebSearchAugmentation, WebSearchResult, WebSearchSource


def _collect_events(job):
    return list(job.iter_events(heartbeat_seconds=0))


class ChatResearchContextTestCase(unittest.TestCase):
    def test_small_context_rebuilds_research_request_from_semantic_state(self):
        calls = []
        search_result = WebSearchResult(
            query="semantic query",
            searched_at="2026-09-01T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/research",
                    title="Research source",
                    hostname="example.com",
                    age="2026-09-01",
                    snippets=("A concise supporting fact",),
                    page_text="Detailed evidence " * 500,
                ),
            ),
        )

        def stream_side_effect(messages, _model, *, tools=None, generation_phase="default"):
            calls.append((messages, tools, generation_phase))
            if generation_phase == "research":
                if len(calls) == 1:
                    yield json.dumps(
                        [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "web_search",
                                    "arguments": json.dumps({"query": "semantic query"}),
                                },
                            }
                        ]
                    )
                    return
                self.assertTrue(any("<research_state>" in str(item.get("content")) for item in messages))
                self.assertFalse(any(item.get("role") == "tool" for item in messages))
                self.assertTrue(
                    any("research and tool-selection phase" in str(item.get("content")) for item in messages)
                )
                yield '<research_complete>{"facts":["A concise supporting fact"]}</research_complete>'
                return
            self.assertIsNone(tools)
            self.assertTrue(any("<final_answer_contract" in str(item.get("content")) for item in messages))
            yield "回答を生成しました。"

        with (
            patch.dict(
                os.environ,
                {
                    "LLM_CONTEXT_WINDOW_OPENAI_GPT_OSS_120B": "2600",
                    "LLM_MAX_TOKENS_RESEARCH": "200",
                    "LLM_MAX_TOKENS_ANSWER": "300",
                    "LLM_CONTEXT_SAFETY_MARGIN_TOKENS": "0",
                },
                clear=False,
            ),
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "複雑な質問"}],
                ),
            ),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream_side_effect),
            patch(
                "services.chat_generation.search_brave_llm_context",
                return_value=search_result,
            ),
        ):
            persisted = []
            job = start_generation_job(
                "guest:semantic-state",
                conversation_messages=[{"role": "user", "content": "複雑な質問"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted.append(response),
            )
            events = _collect_events(job)

        self.assertEqual(len(calls), 3)
        self.assertEqual(len(persisted), 1)
        self.assertIn("回答を生成しました。", persisted[0])
        self.assertIn("done", " ".join(event.event for event in events))
        self.assertNotIn("参照した情報が多すぎて", " ".join(str(event.payload) for event in events))

    def test_provider_research_context_rejection_transitions_to_answer_projection(self):
        calls = []

        def stream_side_effect(messages, _model, *, tools=None, generation_phase="default"):
            calls.append((messages, tools, generation_phase))
            if generation_phase == "research":
                raise LlmInputLimitError("provider context window is smaller than estimated")
            self.assertIsNone(tools)
            yield "既知の情報で回答します。"

        with (
            patch.dict(
                os.environ,
                {
                    "LLM_CONTEXT_WINDOW_OPENAI_GPT_OSS_120B": "2600",
                    "LLM_MAX_TOKENS_RESEARCH": "200",
                    "LLM_MAX_TOKENS_ANSWER": "300",
                    "LLM_CONTEXT_SAFETY_MARGIN_TOKENS": "0",
                },
                clear=False,
            ),
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "複雑な質問"}],
                ),
            ),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream_side_effect),
        ):
            persisted = []
            job = start_generation_job(
                "guest:provider-research-overflow",
                conversation_messages=[{"role": "user", "content": "複雑な質問"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted.append(response),
            )
            events = _collect_events(job)

        self.assertEqual([phase for _, _, phase in calls], ["research", "final_answer_deep"])
        self.assertEqual(len(persisted), 1)
        self.assertIn("既知の情報で回答します。", persisted[0])
        self.assertIn("done", " ".join(event.event for event in events))

    def test_wrapup_provider_rejection_still_reaches_final_answer(self):
        calls = []
        search_result = WebSearchResult(
            query="bounded query",
            searched_at="2026-09-01T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/bounded",
                    title="Bounded source",
                    hostname="example.com",
                    age="2026-09-01",
                    snippets=("bounded evidence",),
                ),
            ),
        )

        def stream_side_effect(messages, _model, *, tools=None, generation_phase="default"):
            calls.append((messages, tools, generation_phase))
            if generation_phase == "research":
                yield json.dumps(
                    [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": "bounded query"}),
                            },
                        }
                    ]
                )
                return
            if generation_phase == "research_wrapup":
                raise LlmInputLimitError("wrapup context rejected by provider")
            self.assertIsNone(tools)
            yield "検索済みの根拠で回答します。"

        with (
            patch.dict(
                os.environ,
                {
                    "CHAT_AGENT_MAX_TOOL_CALLS": "1",
                    "LLM_CONTEXT_WINDOW_OPENAI_GPT_OSS_120B": "2600",
                    "LLM_MAX_TOKENS_RESEARCH": "200",
                    "LLM_MAX_TOKENS_ANSWER": "300",
                    "LLM_CONTEXT_SAFETY_MARGIN_TOKENS": "0",
                },
                clear=False,
            ),
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "上限まで調べる質問"}],
                ),
            ),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream_side_effect),
            patch("services.chat_generation.search_brave_llm_context", return_value=search_result),
        ):
            persisted = []
            job = start_generation_job(
                "guest:provider-wrapup-overflow",
                conversation_messages=[{"role": "user", "content": "上限まで調べる質問"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response: persisted.append(response),
            )
            events = _collect_events(job)

        self.assertEqual(
            [phase for _, _, phase in calls],
            ["research", "research_wrapup", "final_answer_deep"],
        )
        self.assertEqual(len(persisted), 1)
        self.assertIn("検索済みの根拠で回答します。", persisted[0])
        self.assertIn("done", " ".join(event.event for event in events))

    def test_final_provider_rejection_retries_with_summary_only_request(self):
        calls = []

        def stream_side_effect(messages, _model, *, tools=None, generation_phase="default"):
            calls.append((messages, tools, generation_phase))
            if len(calls) == 1:
                raise LlmInputLimitError("provider rejected the first answer request")
            self.assertIsNone(tools)
            self.assertTrue(any("<final_answer_contract" in str(item.get("content")) for item in messages))
            yield "要約だけでも回答できました。"

        selected_trace = [
            SelectedReferenceLookupTrace(
                source="shared_prompt_search",
                query="question",
                payload={
                    "status": "ok",
                    "prompts": [{"prompt_id": "p1", "title": "Prompt", "content": "evidence"}],
                },
            )
        ]

        with (
            patch.dict(
                os.environ,
                {
                    "CHAT_WEB_SEARCH_ENABLED": "0",
                    "LLM_CONTEXT_WINDOW_OPENAI_GPT_OSS_120B": "2600",
                    "LLM_MAX_TOKENS_ANSWER": "300",
                    "LLM_CONTEXT_SAFETY_MARGIN_TOKENS": "0",
                },
                clear=False,
            ),
            patch(
                "services.chat_generation.maybe_augment_messages_with_web_search",
                return_value=WebSearchAugmentation(
                    messages=[{"role": "user", "content": "参照を使う質問"}],
                ),
            ),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream_side_effect),
        ):
            persisted = []
            job = start_generation_job(
                "guest:provider-final-overflow",
                conversation_messages=[{"role": "user", "content": "参照を使う質問"}],
                model="openai/gpt-oss-120b",
                selected_reference_trace=selected_trace,
                persist_response=lambda response: persisted.append(response),
            )
            events = _collect_events(job)

        self.assertEqual([phase for _, _, phase in calls], ["final_answer_deep", "final_answer_deep"])
        self.assertEqual(len(persisted), 1)
        self.assertIn("要約だけでも回答できました。", persisted[0])
        self.assertIn("done", " ".join(event.event for event in events))


if __name__ == "__main__":
    unittest.main()
