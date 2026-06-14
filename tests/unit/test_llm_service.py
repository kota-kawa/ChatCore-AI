import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services import llm


# 日本語: mock openai response に関する処理の入口です。
# English: Entry point for logic related to mock openai response.
def _mock_openai_response(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


# 日本語: mock stream chunk に関する処理の入口です。
# English: Entry point for logic related to mock stream chunk.
def _mock_stream_chunk(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
    )


# 日本語: mock tool call chunk に関する処理の入口です。
# English: Entry point for logic related to mock tool call chunk.
def _mock_tool_call_chunk(*, index=0, call_id=None, name=None, arguments=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=index,
                            id=call_id,
                            type="function" if call_id else None,
                            function=SimpleNamespace(name=name, arguments=arguments),
                        )
                    ],
                )
            )
        ]
    )


# 日本語: MockStream に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MockStream.
class _MockStream(list):
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, *items):
        super().__init__(items)
        self.closed = False

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: LlmServiceTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to LlmServiceTestCase.
class LlmServiceTestCase(unittest.TestCase):
    # 日本語: test prepare openai responses input converts system to developer and reenables markdown のテスト検証を担当します。
    # English: Handle verifying test behavior for test prepare openai responses input converts system to developer and reenables markdown.
    def test_prepare_openai_responses_input_converts_system_to_developer_and_reenables_markdown(self):
        prepared = llm._prepare_openai_responses_input(
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "system", "content": "Follow the task contract."},
                {"role": "user", "content": "hello"},
            ]
        )

        self.assertEqual(prepared[0]["role"], "developer")
        self.assertTrue(
            prepared[0]["content"].startswith(f"{llm.OPENAI_MARKDOWN_REENABLE_PREFIX}\n")
        )
        self.assertEqual(prepared[1]["role"], "developer")
        self.assertFalse(
            prepared[1]["content"].startswith(f"{llm.OPENAI_MARKDOWN_REENABLE_PREFIX}\n")
        )
        self.assertEqual(prepared[2]["role"], "user")

    # 日本語: test get llm response routes to groq のテスト検証を担当します。
    # English: Handle verifying test behavior for test get llm response routes to groq.
    def test_get_llm_response_routes_to_groq(self):
        mock_groq = MagicMock()
        mock_groq.chat.completions.create.return_value = _mock_openai_response("groq-ok")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "groq_client", mock_groq):
            response = llm.get_llm_response(
                [{"role": "user", "content": "hello"}],
                llm.GROQ_MODEL,
            )

        self.assertEqual(response, "groq-ok")
        mock_groq.chat.completions.create.assert_called_once()

    # 日本語: test get llm response routes to gemini のテスト検証を担当します。
    # English: Handle verifying test behavior for test get llm response routes to gemini.
    def test_get_llm_response_routes_to_gemini(self):
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create.return_value = _mock_openai_response(
            "gemini-ok"
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "gemini_client", mock_gemini):
            response = llm.get_llm_response(
                [{"role": "user", "content": "hello"}],
                "gemini-2.5-flash",
            )

        self.assertEqual(response, "gemini-ok")
        mock_gemini.chat.completions.create.assert_called_once()

    # 日本語: test gemini api key accepts standard uppercase env name のテスト検証を担当します。
    # English: Handle verifying test behavior for test gemini api key accepts standard uppercase env name.
    def test_gemini_api_key_accepts_standard_uppercase_env_name(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.dict(
            llm.os.environ,
            {"GEMINI_API_KEY": "standard-key", "Gemini_API_KEY": ""},
            clear=False,
        ):
            self.assertEqual(llm._get_gemini_api_key(), "standard-key")

    # 日本語: test get llm response routes to openai responses のテスト検証を担当します。
    # English: Handle verifying test behavior for test get llm response routes to openai responses.
    def test_get_llm_response_routes_to_openai_responses(self):
        mock_openai = MagicMock()
        mock_openai.responses.create.return_value = SimpleNamespace(output_text="openai-ok")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "openai_client", mock_openai):
            response = llm.get_llm_response(
                [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "hello"},
                ],
                llm.GPT_5_MINI_MODEL,
            )

        self.assertEqual(response, "openai-ok")
        mock_openai.responses.create.assert_called_once()
        passed_messages = mock_openai.responses.create.call_args.kwargs["input"]
        self.assertEqual(passed_messages[0]["role"], "developer")
        self.assertTrue(
            passed_messages[0]["content"].startswith(f"{llm.OPENAI_MARKDOWN_REENABLE_PREFIX}\n")
        )

    # 日本語: test get llm response rejects invalid model のテスト検証を担当します。
    # English: Handle verifying test behavior for test get llm response rejects invalid model.
    def test_get_llm_response_rejects_invalid_model(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaises(llm.LlmInvalidModelError) as cm:
            llm.get_llm_response(
                [{"role": "user", "content": "hello"}],
                "invalid-model",
            )

        self.assertIn("無効なモデル", str(cm.exception))

    # 日本語: test get llm response redacts sensitive values before provider call のテスト検証を担当します。
    # English: Handle verifying test behavior for test get llm response redacts sensitive values before provider call.
    def test_get_llm_response_redacts_sensitive_values_before_provider_call(self):
        mock_groq = MagicMock()
        mock_groq.chat.completions.create.return_value = _mock_openai_response("ok")
        input_message = "api_key=sk-abcdefghijklmnopqrstuvwxyz012345"

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "groq_client", mock_groq):
            response = llm.get_llm_response(
                [{"role": "user", "content": input_message}],
                llm.GROQ_MODEL,
            )

        self.assertEqual(response, "ok")
        passed_messages = mock_groq.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(len(passed_messages), 1)
        self.assertNotIn("sk-", passed_messages[0]["content"])
        self.assertIn("REDACTED-SENSITIVE", passed_messages[0]["content"])

    # 日本語: test get groq response raises configuration error without api key のテスト検証を担当します。
    # English: Handle verifying test behavior for test get groq response raises configuration error without api key.
    def test_get_groq_response_raises_configuration_error_without_api_key(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "groq_client", None):
            with self.assertRaises(llm.LlmConfigurationError):
                llm.get_groq_response(
                    [{"role": "user", "content": "hello"}],
                    llm.GROQ_MODEL,
                )

    # 日本語: test get gemini response wraps provider error as exception のテスト検証を担当します。
    # English: Handle verifying test behavior for test get gemini response wraps provider error as exception.
    def test_get_gemini_response_wraps_provider_error_as_exception(self):
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create.side_effect = RuntimeError("provider down")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "gemini_client", mock_gemini):
            with self.assertRaises(llm.LlmProviderError):
                llm.get_gemini_response(
                    [{"role": "user", "content": "hello"}],
                    "gemini-2.5-flash",
                )

    # 日本語: test get gemini response maps rate limit error のテスト検証を担当します。
    # English: Handle verifying test behavior for test get gemini response maps rate limit error.
    def test_get_gemini_response_maps_rate_limit_error(self):
        # 日本語: FakeRateLimitError として扱う例外情報を表します。
        # English: Represent exception details handled as FakeRateLimitError.
        class FakeRateLimitError(Exception):
            pass

        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create.side_effect = FakeRateLimitError("rate limit")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "RateLimitError", FakeRateLimitError):
            with patch.object(llm, "gemini_client", mock_gemini):
                with self.assertRaises(llm.LlmRateLimitError) as cm:
                    llm.get_gemini_response(
                        [{"role": "user", "content": "hello"}],
                        "gemini-2.5-flash",
                    )

        self.assertTrue(llm.is_retryable_llm_error(cm.exception))

    # 日本語: test get gemini response maps timeout error のテスト検証を担当します。
    # English: Handle verifying test behavior for test get gemini response maps timeout error.
    def test_get_gemini_response_maps_timeout_error(self):
        # 日本語: FakeTimeoutError として扱う例外情報を表します。
        # English: Represent exception details handled as FakeTimeoutError.
        class FakeTimeoutError(Exception):
            pass

        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create.side_effect = FakeTimeoutError("timeout")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "APITimeoutError", FakeTimeoutError):
            with patch.object(llm, "gemini_client", mock_gemini):
                with self.assertRaises(llm.LlmTimeoutError) as cm:
                    llm.get_gemini_response(
                        [{"role": "user", "content": "hello"}],
                        "gemini-2.5-flash",
                    )

        self.assertTrue(llm.is_retryable_llm_error(cm.exception))

    # 日本語: test get gemini response maps authentication error のテスト検証を担当します。
    # English: Handle verifying test behavior for test get gemini response maps authentication error.
    def test_get_gemini_response_maps_authentication_error(self):
        # 日本語: FakeAuthError として扱う例外情報を表します。
        # English: Represent exception details handled as FakeAuthError.
        class FakeAuthError(Exception):
            pass

        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create.side_effect = FakeAuthError("auth")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "AuthenticationError", FakeAuthError):
            with patch.object(llm, "gemini_client", mock_gemini):
                with self.assertRaises(llm.LlmAuthenticationError) as cm:
                    llm.get_gemini_response(
                        [{"role": "user", "content": "hello"}],
                        "gemini-2.5-flash",
                    )

        self.assertFalse(llm.is_retryable_llm_error(cm.exception))

    # 日本語: test get openai response raises configuration error without api key のテスト検証を担当します。
    # English: Handle verifying test behavior for test get openai response raises configuration error without api key.
    def test_get_openai_response_raises_configuration_error_without_api_key(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "openai_client", None):
            with self.assertRaises(llm.LlmConfigurationError):
                llm.get_openai_response(
                    [{"role": "user", "content": "hello"}],
                    llm.GPT_5_MINI_MODEL,
                )

    # 日本語: test get gemini response stream yields chunks and closes stream のテスト検証を担当します。
    # English: Handle verifying test behavior for test get gemini response stream yields chunks and closes stream.
    def test_get_gemini_response_stream_yields_chunks_and_closes_stream(self):
        mock_gemini = MagicMock()
        mock_stream = _MockStream(
            _mock_stream_chunk("gemini"),
            _mock_stream_chunk(None),
            _mock_stream_chunk("-stream"),
        )
        mock_gemini.chat.completions.create.return_value = mock_stream

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "gemini_client", mock_gemini):
            response = list(
                llm.get_gemini_response_stream(
                    [{"role": "user", "content": "hello"}],
                    "gemini-2.5-flash",
                )
            )

        self.assertEqual(response, ["gemini", "-stream"])
        self.assertTrue(mock_stream.closed)
        self.assertTrue(mock_gemini.chat.completions.create.call_args.kwargs["stream"])

    # 日本語: test get gemini response stream sends tool choice when tools are present のテスト検証を担当します。
    # English: Handle verifying test behavior for test get gemini response stream sends tool choice when tools are present.
    def test_get_gemini_response_stream_sends_tool_choice_when_tools_are_present(self):
        mock_gemini = MagicMock()
        mock_stream = _MockStream(_mock_stream_chunk("gemini"))
        mock_gemini.chat.completions.create.return_value = mock_stream
        tools = [{"type": "function", "function": {"name": "web_search"}}]

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "gemini_client", mock_gemini):
            response = list(
                llm.get_gemini_response_stream(
                    [{"role": "user", "content": "hello"}],
                    "gemini-2.5-flash",
                    tools=tools,
                )
            )

        self.assertEqual(response, ["gemini"])
        request_kwargs = mock_gemini.chat.completions.create.call_args.kwargs
        self.assertEqual(request_kwargs["tools"], tools)
        self.assertEqual(request_kwargs["tool_choice"], "auto")

    # 日本語: test get groq response stream yields chunks and closes stream のテスト検証を担当します。
    # English: Handle verifying test behavior for test get groq response stream yields chunks and closes stream.
    def test_get_groq_response_stream_yields_chunks_and_closes_stream(self):
        mock_groq = MagicMock()
        mock_stream = _MockStream(
            _mock_stream_chunk("groq"),
            _mock_stream_chunk(None),
            _mock_stream_chunk("-stream"),
        )
        mock_groq.chat.completions.create.return_value = mock_stream

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "groq_client", mock_groq):
            response = list(
                llm.get_groq_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.GROQ_MODEL,
                )
            )

        self.assertEqual(response, ["groq", "-stream"])
        self.assertTrue(mock_stream.closed)
        self.assertTrue(mock_groq.chat.completions.create.call_args.kwargs["stream"])

    # 日本語: test get groq response stream aggregates tool call chunks のテスト検証を担当します。
    # English: Handle verifying test behavior for test get groq response stream aggregates tool call chunks.
    def test_get_groq_response_stream_aggregates_tool_call_chunks(self):
        mock_groq = MagicMock()
        mock_stream = _MockStream(
            _mock_tool_call_chunk(
                call_id="call-1",
                name="web_search",
                arguments='{"query": ',
            ),
            _mock_tool_call_chunk(arguments='"OpenAI latest news"}'),
        )
        mock_groq.chat.completions.create.return_value = mock_stream

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "groq_client", mock_groq):
            response = list(
                llm.get_groq_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.GROQ_MODEL,
                    tools=[{"type": "function", "function": {"name": "web_search"}}],
                )
            )

        tool_calls = json.loads(response[0])
        self.assertEqual(tool_calls[0]["id"], "call-1")
        self.assertEqual(tool_calls[0]["function"]["name"], "web_search")
        self.assertEqual(
            json.loads(tool_calls[0]["function"]["arguments"]),
            {"query": "OpenAI latest news"},
        )
        self.assertTrue(mock_stream.closed)

    # 日本語: test get llm response stream routes to groq のテスト検証を担当します。
    # English: Handle verifying test behavior for test get llm response stream routes to groq.
    def test_get_llm_response_stream_routes_to_groq(self):
        messages = [{"role": "user", "content": "hello"}]
        tools = [{"type": "function", "function": {"name": "web_search"}}]
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(
            llm,
            "get_groq_response_stream",
            return_value=iter(["groq", "-stream"]),
        ) as mock_stream:
            response = list(
                llm.get_llm_response_stream(
                    messages,
                    llm.GROQ_MODEL,
                    tools=tools,
                )
            )

        self.assertEqual(response, ["groq", "-stream"])
        mock_stream.assert_called_once_with(messages, llm.GROQ_MODEL, tools=tools)

    # 日本語: test get openai response stream yields text deltas のテスト検証を担当します。
    # English: Handle verifying test behavior for test get openai response stream yields text deltas.
    def test_get_openai_response_stream_yields_text_deltas(self):
        mock_openai = MagicMock()
        mock_event1 = MagicMock()
        mock_event1.type = "response.output_text.delta"
        mock_event1.delta = "openai"
        mock_event2 = MagicMock()
        mock_event2.type = "response.output_text.delta"
        mock_event2.delta = "-stream"
        mock_stream = MagicMock()
        mock_stream.__iter__ = MagicMock(return_value=iter([mock_event1, mock_event2]))
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__enter__.return_value = mock_stream
        mock_stream_ctx.__exit__.return_value = None
        mock_openai.responses.stream.return_value = mock_stream_ctx

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "openai_client", mock_openai):
            response = list(
                llm.get_openai_response_stream(
                    [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "hello"},
                    ],
                    llm.GPT_5_MINI_MODEL,
                )
            )

        self.assertEqual(response, ["openai", "-stream"])
        mock_openai.responses.stream.assert_called_once()
        passed_messages = mock_openai.responses.stream.call_args.kwargs["input"]
        self.assertEqual(passed_messages[0]["role"], "developer")
        self.assertTrue(
            passed_messages[0]["content"].startswith(f"{llm.OPENAI_MARKDOWN_REENABLE_PREFIX}\n")
        )

    # 日本語: test get openai response stream with tools uses chat completions stream のテスト検証を担当します。
    # English: Handle verifying test behavior for test get openai response stream with tools uses chat completions stream.
    def test_get_openai_response_stream_with_tools_uses_chat_completions_stream(self):
        mock_openai = MagicMock()
        mock_stream = _MockStream(_mock_stream_chunk("tool"), _mock_stream_chunk("-stream"))
        mock_openai.chat.completions.create.return_value = mock_stream

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "openai_client", mock_openai):
            response = list(
                llm.get_openai_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.GPT_5_MINI_MODEL,
                    tools=[{"type": "function", "function": {"name": "web_search"}}],
                )
            )

        self.assertEqual(response, ["tool", "-stream"])
        mock_openai.chat.completions.create.assert_called_once()
        chat_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        self.assertEqual(chat_kwargs["max_completion_tokens"], llm.LLM_MAX_TOKENS)
        self.assertNotIn("max_tokens", chat_kwargs)
        self.assertEqual(chat_kwargs["tool_choice"], "auto")
        mock_openai.responses.stream.assert_not_called()
        self.assertTrue(mock_stream.closed)

    # 日本語: test get openai response stream with tool history uses chat completions のテスト検証を担当します。
    # English: Handle verifying test behavior for test get openai response stream with tool history uses chat completions.
    def test_get_openai_response_stream_with_tool_history_uses_chat_completions(self):
        mock_openai = MagicMock()
        mock_stream = _MockStream(_mock_stream_chunk("final"))
        mock_openai.chat.completions.create.return_value = mock_stream

        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query":"OpenAI news"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "web_search",
                "content": '{"status":"completed"}',
            },
        ]

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(llm, "openai_client", mock_openai):
            response = list(llm.get_openai_response_stream(messages, llm.GPT_5_MINI_MODEL))

        self.assertEqual(response, ["final"])
        mock_openai.chat.completions.create.assert_called_once()
        chat_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        self.assertNotIn("tools", chat_kwargs)
        self.assertNotIn("tool_choice", chat_kwargs)
        mock_openai.responses.stream.assert_not_called()
        self.assertTrue(mock_stream.closed)

    # 日本語: test get llm response stream routes to openai のテスト検証を担当します。
    # English: Handle verifying test behavior for test get llm response stream routes to openai.
    def test_get_llm_response_stream_routes_to_openai(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(
            llm,
            "get_openai_response_stream",
            return_value=iter(["openai", "-stream"]),
        ) as mock_stream:
            response = list(
                llm.get_llm_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.GPT_5_MINI_MODEL,
                )
            )

        self.assertEqual(response, ["openai", "-stream"])
        mock_stream.assert_called_once()


if __name__ == "__main__":
    unittest.main()
