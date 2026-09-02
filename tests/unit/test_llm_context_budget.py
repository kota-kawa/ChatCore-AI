import json
import os
import unittest
from unittest.mock import patch

from services.llm_context_budget import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    GPT_OSS_120B_MODEL,
    MODEL_CONTEXT_WINDOWS,
    LlmContextBudget,
    estimate_messages_tokens,
    estimate_request_tokens,
    estimate_tools_tokens,
    get_available_input_tokens,
    get_context_budget,
    get_model_context_window,
    get_output_reserved_tokens,
    request_fits_context,
)


class LlmContextBudgetTestCase(unittest.TestCase):
    def test_known_models_have_explicit_context_windows(self):
        self.assertEqual(
            get_model_context_window(GPT_OSS_120B_MODEL),
            MODEL_CONTEXT_WINDOWS[GPT_OSS_120B_MODEL],
        )
        self.assertGreater(
            get_model_context_window("claude-haiku-4-5-20251001"),
            DEFAULT_CONTEXT_WINDOW_TOKENS,
        )

    def test_unknown_model_uses_conservative_fallback(self):
        unknown_window = get_model_context_window("vendor/new-model")

        self.assertEqual(unknown_window, DEFAULT_CONTEXT_WINDOW_TOKENS)
        self.assertLess(
            unknown_window,
            min(MODEL_CONTEXT_WINDOWS.values()),
        )

    def test_model_specific_context_override_wins_over_global_override(self):
        with patch.dict(
            os.environ,
            {
                "LLM_CONTEXT_WINDOW_TOKENS": "70000",
                "LLM_CONTEXT_WINDOW_OPENAI_GPT_OSS_120B": "90000",
            },
        ):
            self.assertEqual(get_model_context_window(GPT_OSS_120B_MODEL), 90000)
            self.assertEqual(get_model_context_window("vendor/new-model"), 70000)

    def test_invalid_context_override_falls_back_safely(self):
        with patch.dict(
            os.environ,
            {"LLM_CONTEXT_WINDOW_OPENAI_GPT_OSS_120B": "not-a-number"},
        ):
            self.assertEqual(
                get_model_context_window(GPT_OSS_120B_MODEL),
                MODEL_CONTEXT_WINDOWS[GPT_OSS_120B_MODEL],
            )

    def test_output_reservation_is_phase_specific(self):
        with patch.dict(
            os.environ,
            {
                "LLM_MAX_TOKENS": "1000",
                "LLM_MAX_TOKENS_ANSWER": "3000",
            },
        ):
            self.assertEqual(get_output_reserved_tokens("default"), 1000)
            # 判断ループも回答を書くため、回答フェーズと同じ出力枠を使う。
            # The decision loop writes the answer too, so it reserves the answer budget.
            self.assertEqual(get_output_reserved_tokens("agent"), 3000)
            self.assertEqual(get_output_reserved_tokens("final_answer"), 3000)
            self.assertEqual(get_output_reserved_tokens("continuation_deep"), 3000)
            # 廃止した調査専用フェーズは既定の出力枠へ落ちる。
            # The retired research-only phase falls back to the general output budget.
            self.assertEqual(get_output_reserved_tokens("research"), 1000)

    def test_invalid_output_environment_values_use_phase_defaults(self):
        with patch.dict(
            os.environ,
            {
                "LLM_MAX_TOKENS": "0",
                "LLM_MAX_TOKENS_ANSWER": "invalid",
            },
        ):
            self.assertGreater(get_output_reserved_tokens("default"), 0)
            self.assertGreater(get_output_reserved_tokens("agent"), 0)
            self.assertGreater(get_output_reserved_tokens("final_answer"), 0)

    def test_message_estimate_includes_metadata_and_tool_calls(self):
        plain = [{"role": "user", "content": "question"}]
        enriched = [
            {
                "role": "assistant",
                "content": None,
                "name": "researcher",
                "tool_calls": [
                    {
                        "id": "call-123",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": json.dumps({"query": "latest news"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-123",
                "name": "web_search",
                "content": [{"type": "text", "text": "result"}],
            },
        ]

        self.assertGreater(estimate_messages_tokens(enriched), estimate_messages_tokens(plain))

    def test_tool_estimate_includes_schema_and_per_tool_overhead(self):
        tool = {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        }

        with patch.dict(os.environ, {"LLM_TOOL_SCHEMA_OVERHEAD_TOKENS": "100"}):
            one_tool = estimate_tools_tokens([tool])
            two_tools = estimate_tools_tokens([tool, tool])

        self.assertGreater(one_tool, 100)
        self.assertGreater(two_tools, one_tool + 100)

    def test_context_budget_subtracts_output_tools_and_safety_margin(self):
        tool = {"type": "function", "function": {"name": "search"}}
        budget = get_context_budget(
            GPT_OSS_120B_MODEL,
            "final_answer",
            [tool],
            output_reserved_tokens=10_000,
            safety_margin_tokens=500,
            tool_schema_tokens=700,
        )

        expected = budget.context_window_tokens - 10_000 - 500 - 700
        self.assertEqual(budget.available_input_tokens, expected)
        self.assertEqual(budget.reserved_tokens, 11_200)
        self.assertIsInstance(budget, LlmContextBudget)

    def test_available_input_never_becomes_negative(self):
        self.assertEqual(
            get_available_input_tokens(
                "vendor/tiny",
                output_reserved_tokens=100_000,
                safety_margin_tokens=100_000,
                tool_schema_tokens=100_000,
            ),
            0,
        )

    def test_complete_request_fit_accounts_for_tool_schema(self):
        messages = [{"role": "user", "content": "question"}]
        tools = [{"type": "function", "function": {"name": "search"}}]
        message_tokens = estimate_messages_tokens(messages)
        tool_tokens = estimate_tools_tokens(tools)

        self.assertEqual(
            estimate_request_tokens(messages, tools),
            message_tokens + tool_tokens,
        )
        self.assertTrue(
            request_fits_context(
                messages,
                "vendor/test",
                output_reserved_tokens=100,
                safety_margin_tokens=100,
                tool_schema_tokens=tool_tokens,
            )
        )

        # A message estimate exactly at the allowance is accepted; one token
        # beyond it is rejected before the provider can see the request.
        budget = get_context_budget(
            "vendor/test",
            "default",
            output_reserved_tokens=100,
            safety_margin_tokens=100,
            tool_schema_tokens=tool_tokens,
        )
        with patch.dict(
            os.environ,
            {"LLM_CONTEXT_WINDOW_VENDOR_TEST": str(budget.available_input_tokens + 200)},
        ):
            boundary_budget = get_context_budget(
                "vendor/test",
                "default",
                output_reserved_tokens=100,
                safety_margin_tokens=100,
                tool_schema_tokens=tool_tokens,
            )
            self.assertTrue(boundary_budget.fits_message_tokens(boundary_budget.available_input_tokens))
            self.assertFalse(
                boundary_budget.fits_message_tokens(boundary_budget.available_input_tokens + 1)
            )

    def test_empty_messages_and_tools_cost_no_input_tokens(self):
        self.assertEqual(estimate_messages_tokens([]), 0)
        self.assertEqual(estimate_tools_tokens([]), 0)
        self.assertEqual(estimate_request_tokens(None, None), 0)


if __name__ == "__main__":
    unittest.main()
