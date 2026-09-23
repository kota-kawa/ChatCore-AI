"""プロンプトキャッシュが効く並び順と、プロバイダごとの区切りを検証する。

Verifies the message order that keeps provider prompt caches effective and the per-provider
cache breakpoints. Provider caches only match from the start of a request, so fixed
instructions and the history must come first and anything that changes per turn or per step
must follow them.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services import llm
from services.chat_agent_budget import AgentStepBudget
from services.chat_generation import ChatGenerationJob
from services.chat_prompt import insert_before_latest_user_message
from services.chat_turn_state import TURN_LOOP_SYSTEM_PROMPT, build_turn_loop_messages
from services.research_state import TURN_STATE_MARKER, TurnState
from services.usage_metering import set_usage_sink
from services.usage_pricing import token_cost_nano_usd
from services.web_search import build_web_search_evidence_policy_message

_BREAKPOINT = {"mode": "explicit"}
_EPHEMERAL = {"type": "ephemeral"}


def _conversation():
    return [
        {"role": "system", "content": "base prompt"},
        {"role": "system", "content": "ui contract"},
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
        {"role": "system", "content": "<runtime_context>now</runtime_context>"},
        {"role": "user", "content": "latest question"},
    ]


class DynamicContextPlacementTests(unittest.TestCase):
    def test_per_turn_context_goes_right_before_the_latest_user_message(self):
        messages = insert_before_latest_user_message(_conversation(), {"role": "system", "content": "state"})
        self.assertEqual(
            [message["content"] for message in messages[-3:]],
            ["<runtime_context>now</runtime_context>", "state", "latest question"],
        )
        self.assertEqual(messages[3]["content"], "earlier answer")

    def test_without_a_user_message_it_falls_back_after_the_system_block(self):
        messages = insert_before_latest_user_message(
            [{"role": "system", "content": "base"}, {"role": "assistant", "content": "hi"}],
            {"role": "system", "content": "state"},
        )
        self.assertEqual([message["content"] for message in messages], ["base", "state", "hi"])

    def test_turn_state_follows_the_history(self):
        projected = TurnState(objective="latest question").projected_messages(_conversation())
        self.assertEqual(projected[3]["content"], "earlier answer")
        self.assertEqual(projected[-1]["content"], "latest question")
        self.assertEqual(projected[-2]["role"], "system")
        self.assertNotEqual(projected[-2]["content"], "<runtime_context>now</runtime_context>")

    # 日本語: 判断ループの契約が TurnState の直後に並ぶことを検証します。離すと GPT-OSS が
    # 更新封筒をツールと取り違えたため、この隣接は壊してはいけません。
    # English: Verify the loop contract directly follows TurnState. Separating them made GPT-OSS
    # mistake the update envelope for a tool call, so this adjacency must hold.
    def test_loop_contract_directly_follows_the_turn_state(self):
        projected = TurnState(objective="latest question").projected_messages(_conversation())
        messages = build_turn_loop_messages(projected)
        self.assertTrue(messages[-3]["content"].startswith(TURN_STATE_MARKER))
        self.assertEqual(messages[-2]["content"], TURN_LOOP_SYSTEM_PROMPT)
        self.assertEqual(messages[-1]["content"], "latest question")
        self.assertEqual(messages[3]["content"], "earlier answer")


    # 日本語: 検索根拠のあるターンでも、TurnState・引用方針・契約が変更前と同じ相対順の
    # まとまりとして最新の発話の直前に並ぶことを、実際の判断ループの組み立てで検証します。
    # English: Verify, through the real loop assembly, that a turn holding web evidence keeps
    # TurnState, the citation policy and the contract as one block in their original order.
    def test_web_evidence_turn_keeps_state_policy_and_contract_together(self):
        job = ChatGenerationJob(
            conversation_messages=_conversation(),
            model=llm.GPT_OSS_120B_MODEL,
            persist_response=MagicMock(),
        )
        state = job._build_turn_run_state()
        state.web_search_results.append(MagicMock())
        messages = job._prepare_turn_messages(state, [], None, force_answer=False)

        contents = [str(message["content"]) for message in messages]
        self.assertTrue(contents[-4].startswith(TURN_STATE_MARKER))
        self.assertEqual(contents[-3], build_web_search_evidence_policy_message()["content"])
        self.assertEqual(contents[-2], TURN_LOOP_SYSTEM_PROMPT)
        self.assertEqual(contents[-1], "latest question")
        self.assertEqual(contents[3], "earlier answer")


class StableToolListTests(unittest.TestCase):
    def _state(self, *, web_search: bool):
        job = ChatGenerationJob(
            conversation_messages=[{"role": "user", "content": "調べて"}],
            model=llm.GPT_OSS_120B_MODEL,
            persist_response=MagicMock(),
        )
        state = job._build_turn_run_state()
        with patch("services.chat_generation.is_web_search_enabled", return_value=web_search):
            job._configure_agent_tools(state)
        return job, state

    def test_read_tools_are_offered_before_any_evidence_when_search_is_available(self):
        job, state = self._state(web_search=True)
        names = [tool["function"]["name"] for tool in job._available_agent_tools(state)]
        self.assertEqual(names, ["web_search", "get_evidence", "read_web_page"])

    def test_without_a_search_tool_read_tools_still_wait_for_evidence(self):
        job, state = self._state(web_search=False)
        self.assertEqual(job._available_agent_tools(state), [])

    def test_exhausted_read_budget_still_withdraws_read_tools(self):
        job, state = self._state(web_search=True)
        state.budget = AgentStepBudget(max_llm_turns=6, max_tool_calls=4, max_read_calls=0)
        names = [tool["function"]["name"] for tool in job._available_agent_tools(state)]
        self.assertEqual(names, ["web_search"])


class OpenAiBreakpointTests(unittest.TestCase):
    def test_luna_chat_marks_the_base_prompt_and_the_history_end(self):
        marked = llm._with_openai_cache_breakpoints(llm.GPT_6_LUNA_MODEL, _conversation(), responses_api=False)
        self.assertEqual(
            marked[0]["content"],
            [{"type": "text", "text": "base prompt", "prompt_cache_breakpoint": _BREAKPOINT}],
        )
        self.assertEqual(marked[3]["content"][0]["prompt_cache_breakpoint"], _BREAKPOINT)
        # 変わる文脈と最新の発話には付けない。 / Never on the changing context or latest message.
        self.assertIsInstance(marked[4]["content"], str)
        self.assertIsInstance(marked[5]["content"], str)

    def test_responses_api_moves_the_history_breakpoint_off_assistant_output(self):
        marked = llm._with_openai_cache_breakpoints(llm.GPT_6_LUNA_MODEL, _conversation(), responses_api=True)
        self.assertIsInstance(marked[3]["content"], str)
        self.assertEqual(
            marked[2]["content"],
            [{"type": "input_text", "text": "earlier question", "prompt_cache_breakpoint": _BREAKPOINT}],
        )

    def test_first_turn_marks_only_the_base_prompt(self):
        messages = [
            {"role": "system", "content": "base prompt"},
            {"role": "system", "content": "<runtime_context>now</runtime_context>"},
            {"role": "user", "content": "hello"},
        ]
        marked = llm._with_openai_cache_breakpoints(llm.GPT_6_LUNA_MODEL, messages, responses_api=False)
        self.assertIsInstance(marked[0]["content"], list)
        self.assertEqual([type(message["content"]) for message in marked[1:]], [str, str])

    def test_groq_models_get_no_breakpoints(self):
        self.assertEqual(
            llm._with_openai_cache_breakpoints(llm.GPT_OSS_120B_MODEL, _conversation(), responses_api=False),
            _conversation(),
        )

    def test_luna_stream_sends_breakpoints_and_groq_stream_does_not(self):
        for model_name, client_name, expected in (
            (llm.GPT_6_LUNA_MODEL, "openai_client", list),
            (llm.GPT_OSS_120B_MODEL, "groq_client", str),
        ):
            client = MagicMock()
            client.chat.completions.create.return_value = MagicMock(__iter__=lambda _self: iter(()))
            tools = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]
            with self.subTest(model_name=model_name), patch.object(llm, client_name, client):
                list(llm.get_llm_response_stream(_conversation(), model_name, tools=tools))
                sent = client.chat.completions.create.call_args.kwargs["messages"]
                self.assertIsInstance(sent[0]["content"], expected)


class ClaudeCacheLayoutTests(unittest.TestCase):
    def test_leading_system_block_is_cached_and_later_system_text_joins_the_user_turn(self):
        system_blocks, messages = llm._prepare_claude_messages(_conversation())

        self.assertEqual(
            system_blocks,
            [
                {"type": "text", "text": "base prompt", "cache_control": _EPHEMERAL},
                {"type": "text", "text": "ui contract"},
            ],
        )
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(
            messages[1]["content"],
            [{"type": "text", "text": "earlier answer", "cache_control": _EPHEMERAL}],
        )
        # 履歴の後ろの実行時文脈は system ではなく、最新のユーザーターンの先頭に入る。
        # The runtime context after the history joins the latest user turn instead of system.
        self.assertEqual(messages[2]["role"], "user")
        self.assertEqual(
            messages[2]["content"],
            "<runtime_context>now</runtime_context>\n\nlatest question",
        )

    def test_request_sends_the_system_blocks(self):
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")], usage=None
        )
        set_usage_sink(lambda _increment: None)
        with patch.object(llm, "claude_client", client):
            llm.get_claude_response(_conversation(), llm.CLAUDE_HAIKU_4_5_MODEL)
        sent = client.messages.create.call_args.kwargs
        self.assertEqual(sent["system"][0]["cache_control"], _EPHEMERAL)


class CacheWritePricingTests(unittest.TestCase):
    def test_cache_writes_are_billed_at_the_premium(self):
        # GPT-6 Luna: input 100, cached 10, cache write 125 nano-dollars per token.
        cost = token_cost_nano_usd(
            llm.GPT_6_LUNA_MODEL,
            input_tokens=1_000,
            cached_input_tokens=600,
            cache_write_input_tokens=300,
            output_tokens=0,
        )
        self.assertEqual(cost, 100 * 100 + 600 * 10 + 300 * 125)

    def test_groq_has_no_write_premium(self):
        self.assertEqual(
            token_cost_nano_usd(llm.GPT_OSS_120B_MODEL, input_tokens=10, cache_write_input_tokens=10, output_tokens=0),
            token_cost_nano_usd(llm.GPT_OSS_120B_MODEL, input_tokens=10, output_tokens=0),
        )


if __name__ == "__main__":
    unittest.main()
