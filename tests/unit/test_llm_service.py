import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services import llm
from services.user_skills import GENERATIVE_UI_EXECUTION_CONTRACT


def _mock_openai_response(text):
    """
    テスト用にOpenAI APIの非ストリーミング型レスポンスオブジェクトをモックします。
    Mock a non-streaming OpenAI API response object for testing.
    """
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def _mock_stream_chunk(text, *, finish_reason=None):
    """
    テスト用にOpenAI APIのストリーミング応答のチャンク（差分）オブジェクトをモックします。
    Mock a streaming OpenAI API response chunk object for testing.
    """
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=text),
                finish_reason=finish_reason,
            )
        ]
    )


def _mock_tool_call_chunk(*, index=0, call_id=None, name=None, arguments=None):
    """
    テスト用にストリーミング応答におけるツール呼び出しチャンクをモックします。
    Mock a tool call chunk in streaming response for testing.
    """
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


class _MockStream(list):
    """
    テスト用にイテラブルなモックストリーム（closeメソッド付き）を表すクラス。
    Mock class representing an iterable stream with a close method for testing.
    """

    def __init__(self, *items):
        """
        指定された要素でストリームを初期化します。
        Initialize the stream with specified items.
        """
        super().__init__(items)
        self.closed = False

    def close(self):
        """
        ストリームを閉じます。
        Close the stream.
        """
        self.closed = True


class LlmServiceTestCase(unittest.TestCase):
    """
    LLMサービス連携におけるAPIクライアントの振り分け、エラーハンドリング、ストリーミングパース等をテストするクラス。
    Test class for verifying API client routing, error mapping, and streaming parsing in LLM service integration.
    """

    def test_prepare_openai_responses_input_converts_system_to_developer_and_reenables_markdown(self):
        """
        OpenAI APIの仕様に合わせ、入力メッセージの"system"ロールが"developer"に変換され、Markdown再有効化接頭辞が適用されることを検証します。
        Verify that input message "system" roles are converted to "developer" and prepend the markdown re-enable prefix for OpenAI API compatibility.
        """
        # メッセージの準備を実行
        # Execute message preparation
        prepared = llm._prepare_openai_responses_input(
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "system", "content": GENERATIVE_UI_EXECUTION_CONTRACT},
                {"role": "user", "content": "hello"},
            ]
        )

        # 各ロールおよびコンテンツの変換結果を検証
        # Verify the converted roles and contents
        self.assertEqual(prepared[0]["role"], "developer")
        self.assertTrue(
            prepared[0]["content"].startswith(f"{llm.OPENAI_MARKDOWN_REENABLE_PREFIX}\n")
        )
        self.assertEqual(prepared[1]["role"], "developer")
        self.assertFalse(
            prepared[1]["content"].startswith(f"{llm.OPENAI_MARKDOWN_REENABLE_PREFIX}\n")
        )
        self.assertEqual(prepared[1]["content"], GENERATIVE_UI_EXECUTION_CONTRACT)
        self.assertIn(
            "An answer that ends with explanation alone is incomplete", prepared[1]["content"]
        )
        self.assertEqual(prepared[2]["role"], "user")

    def test_prepare_claude_messages_converts_system_and_tool_history(self):
        """Claude Messages APIのsystem promptとツール履歴変換を検証する。"""
        system_prompt, messages = llm._prepare_claude_messages(
            [
                {"role": "system", "content": "You are helpful."},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {
                                "name": "web_search",
                                "arguments": '{"query":"Claude"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "content": '{"status":"completed"}',
                },
            ]
        )

        self.assertEqual(system_prompt, "You are helpful.")
        self.assertEqual(messages[0]["role"], "assistant")
        self.assertEqual(messages[0]["content"][0]["type"], "tool_use")
        self.assertEqual(messages[0]["content"][0]["input"], {"query": "Claude"})
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"][0]["type"], "tool_result")

    # 日本語: ツール結果の user ターン直後にテキストの user ターンを足しても、Claude 側で
    # 同ロールが連続せず1ターンへマージされることを検証します。
    # English: Verify a text user turn appended right after tool results merges into the same
    # Claude turn instead of producing two consecutive user turns.
    def test_prepare_claude_messages_merges_consecutive_same_role_turns(self):
        _, messages = llm._prepare_claude_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {"name": "web_search", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call-1", "content": "{}"},
                {"role": "user", "content": "answer contract"},
            ]
        )

        roles = [message["role"] for message in messages]
        self.assertEqual(roles, ["assistant", "user"])
        self.assertEqual(
            [block["type"] for block in messages[1]["content"]],
            ["tool_result", "text"],
        )
        self.assertEqual(messages[1]["content"][1]["text"], "answer contract")

    # 日本語: 連続するテキストの同ロールも1ターンへまとめられることを検証します。
    # English: Verify consecutive plain-text turns of the same role are merged as well.
    def test_prepare_claude_messages_merges_consecutive_text_turns(self):
        _, messages = llm._prepare_claude_messages(
            [
                {"role": "user", "content": "first"},
                {"role": "user", "content": "second"},
            ]
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "first\n\nsecond")

    # 日本語: 入力（コンテキスト長）超過を出力上限と混同しないことを検証します。継続生成へ
    # 回すと入力がさらに増えて必ず再失敗するため、別の例外である必要があります。
    # English: Verify an input/context overflow is never confused with an output limit: routing
    # it into continuation only grows the request and guarantees another failure.
    def test_get_claude_response_stream_raises_input_limit_for_context_overflow(self):
        mock_claude = MagicMock()
        mock_stream = _MockStream(
            SimpleNamespace(
                type="message_delta",
                delta=SimpleNamespace(stop_reason="model_context_window_exceeded"),
            ),
        )
        mock_claude.messages.create.return_value = mock_stream

        with patch.object(llm, "claude_client", mock_claude):
            stream = llm.get_claude_response_stream(
                [{"role": "user", "content": "hello"}],
                llm.CLAUDE_HAIKU_4_5_MODEL,
            )
            with self.assertRaises(llm.LlmInputLimitError):
                list(stream)

        self.assertTrue(mock_stream.closed)

    # 日本語: OpenAI互換APIが返す context_length_exceeded (400) を入力超過として分類し、
    # 汎用の「内部エラー」に落とさないことを検証します。
    # English: Verify an OpenAI-compatible context_length_exceeded (400) is classified as an
    # input limit rather than collapsing into a generic internal error.
    def test_provider_error_mapping_detects_context_length_exceeded(self):
        class _FakeStatusError(Exception):
            status_code = 400
            body = {
                "error": {
                    "code": "context_length_exceeded",
                    "message": "This model's maximum context length is 131072 tokens.",
                }
            }

        with patch.object(llm, "APIStatusError", _FakeStatusError):
            mapped = llm._map_provider_exception(
                _FakeStatusError("bad request"),
                provider_name="Groq",
                fallback_message="Groq streaming API call failed.",
            )

        self.assertIsInstance(mapped, llm.LlmInputLimitError)

    # 日本語: 出力枠がフェーズごとに分かれ、本文を書く回答フェーズが最大になることを検証します。
    # English: Verify the output budget is split per phase and the answer phase gets the largest.
    def test_output_token_budget_is_split_by_generation_phase(self):
        self.assertEqual(
            llm.max_output_tokens_for_phase("research"),
            llm.LLM_RESEARCH_MAX_TOKENS,
        )
        self.assertEqual(
            llm.max_output_tokens_for_phase("research_wrapup"),
            llm.LLM_RESEARCH_MAX_TOKENS,
        )
        for phase in ("final_answer", "final_answer_deep", "continuation", "continuation_deep"):
            self.assertEqual(
                llm.max_output_tokens_for_phase(phase),
                llm.LLM_ANSWER_MAX_TOKENS,
            )
        self.assertEqual(llm.max_output_tokens_for_phase("default"), llm.LLM_MAX_TOKENS)
        # 本文を書くフェーズは調査ステップより大きくなければならない。
        # The answer phase must be larger than a research step.
        self.assertGreater(llm.LLM_ANSWER_MAX_TOKENS, llm.LLM_RESEARCH_MAX_TOKENS)

    # 日本語: Claudeにも生成フェーズが伝わり、回答フェーズの出力枠が適用されることを検証します。
    # English: Verify the generation phase reaches Claude so the answer budget applies there too.
    def test_claude_stream_applies_phase_specific_output_budget(self):
        mock_claude = MagicMock()
        mock_claude.messages.create.return_value = _MockStream()

        with patch.object(llm, "claude_client", mock_claude):
            list(
                llm.get_llm_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.CLAUDE_HAIKU_4_5_MODEL,
                    generation_phase="final_answer_deep",
                )
            )

        self.assertEqual(
            mock_claude.messages.create.call_args.kwargs["max_tokens"],
            llm.LLM_ANSWER_MAX_TOKENS,
        )

    # 日本語: 出力上限で打ち切られても、収集済みのツール呼び出しを例外より先に流すことを検証します。
    # English: Verify tool calls collected before an output cut-off are emitted before raising.
    def test_output_limited_stream_emits_tool_calls_before_raising(self):
        mock_groq = MagicMock()
        mock_groq.chat.completions.create.return_value = _MockStream(
            _mock_tool_call_chunk(
                call_id="call-1",
                name="web_search",
                arguments='{"query":"x"}',
            ),
            _mock_stream_chunk(None, finish_reason="length"),
        )

        emitted = []
        with patch.object(llm, "groq_client", mock_groq):
            stream = llm.get_groq_response_stream(
                [{"role": "user", "content": "hello"}],
                llm.GROQ_MODEL,
                generation_phase="research",
            )
            with self.assertRaises(llm.LlmOutputLimitError):
                for chunk in stream:
                    emitted.append(chunk)

        self.assertEqual(len(emitted), 1)
        self.assertEqual(json.loads(emitted[0])[0]["function"]["name"], "web_search")

    # 日本語: 調査を伴うターンの回答フェーズでは、思考量を最小へ落とさないことを検証します。
    # English: Verify the answer phase of a research turn does not run on the smallest budget.
    def test_deep_answer_phase_keeps_a_larger_groq_reasoning_budget(self):
        mock_groq = MagicMock()
        mock_groq.chat.completions.create.return_value = _MockStream(
            _mock_stream_chunk("answer")
        )

        with patch.object(llm, "groq_client", mock_groq):
            list(
                llm.get_groq_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.GROQ_MODEL,
                    generation_phase="final_answer_deep",
                )
            )

        extra_body = mock_groq.chat.completions.create.call_args.kwargs["extra_body"]
        self.assertEqual(extra_body["reasoning_effort"], "medium")

    def test_model_constants_ignore_model_environment_variables(self):
        with patch.dict(
            llm.os.environ,
            {
                "GROQ_MODEL": "env-groq-model",
                "OPENAI_DEFAULT_MODEL": "env-openai-model",
                "CLAUDE_DEFAULT_MODEL": "env-claude-model",
            },
            clear=False,
        ):
            self.assertEqual(llm.GROQ_MODEL, llm.GPT_OSS_120B_MODEL)
            self.assertEqual(llm.OPENAI_DEFAULT_MODEL, llm.GPT_5_6_LUNA_MODEL)
            self.assertEqual(llm.CLAUDE_DEFAULT_MODEL, llm.CLAUDE_HAIKU_4_5_MODEL)

    def test_get_claude_response_redacts_anthropic_api_keys(self):
        mock_claude = MagicMock()
        mock_claude.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")]
        )

        with patch.object(llm, "claude_client", mock_claude):
            response = llm.get_claude_response(
                [{"role": "user", "content": "token=sk-ant-abcdefghijklmnopqrstuvwxyz0123456789"}],
                llm.CLAUDE_HAIKU_4_5_MODEL,
            )

        self.assertEqual(response, "ok")
        sent_content = mock_claude.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertNotIn("sk-ant-", sent_content)
        self.assertIn("REDACTED-SENSITIVE", sent_content)

    def test_get_llm_response_routes_to_groq(self):
        """
        モデル名がGroqのものだった場合に、Groqクライアントへ正しく振り分けられることを検証します。
        Verify that requests are correctly routed to the Groq client when the model name matches a Groq model.
        """
        # Groqクライアントのモック作成
        # Create a mock for the Groq client
        mock_groq = MagicMock()
        mock_groq.chat.completions.create.return_value = _mock_openai_response("groq-ok")

        with patch.object(llm, "groq_client", mock_groq):
            response = llm.get_llm_response(
                [{"role": "user", "content": "hello"}],
                llm.GROQ_MODEL,
            )

        # レスポンスおよび呼び出し履歴の検証
        # Assert the response and the invocation
        self.assertEqual(response, "groq-ok")
        mock_groq.chat.completions.create.assert_called_once()
        request_kwargs = mock_groq.chat.completions.create.call_args.kwargs
        self.assertFalse(request_kwargs["extra_body"]["include_reasoning"])
        self.assertNotIn("reasoning_effort", request_kwargs["extra_body"])

    def test_get_llm_response_routes_qwen_to_groq(self):
        mock_groq = MagicMock()
        mock_groq.chat.completions.create.return_value = _mock_openai_response("qwen-ok")

        with patch.object(llm, "groq_client", mock_groq):
            response = llm.get_llm_response(
                [{"role": "user", "content": "hello"}],
                llm.QWEN_3_6_27B_MODEL,
            )

        self.assertEqual(response, "qwen-ok")
        self.assertEqual(
            mock_groq.chat.completions.create.call_args.kwargs["model"],
            llm.QWEN_3_6_27B_MODEL,
        )
        request_kwargs = mock_groq.chat.completions.create.call_args.kwargs
        self.assertEqual(request_kwargs["extra_body"]["reasoning_effort"], "default")
        self.assertEqual(request_kwargs["extra_body"]["reasoning_format"], "hidden")
        self.assertNotIn("include_reasoning", request_kwargs["extra_body"])

    def test_get_llm_response_routes_to_claude(self):
        """
        Claudeモデルが指定された場合に、Claudeクライアントへ正しく振り分けられることを検証します。
        Verify that requests are correctly routed to the Claude client when the model name matches a Claude model.
        """
        mock_claude = MagicMock()
        mock_claude.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="claude-ok")]
        )

        with patch.object(llm, "claude_client", mock_claude):
            response = llm.get_llm_response(
                [{"role": "user", "content": "hello"}],
                llm.CLAUDE_HAIKU_4_5_MODEL,
            )

        self.assertEqual(response, "claude-ok")
        request_kwargs = mock_claude.messages.create.call_args.kwargs
        self.assertEqual(request_kwargs["model"], llm.CLAUDE_HAIKU_4_5_MODEL)
        self.assertEqual(request_kwargs["messages"], [{"role": "user", "content": "hello"}])

    def test_get_llm_response_routes_to_openai_responses(self):
        """
        モデル名がOpenAIの最新のものだった場合に、OpenAI client.responses.createへ振り分けられメッセージ形式が変換されることを検証します。
        Verify that requests are routed to OpenAI's client.responses.create and the input structure is updated for OpenAI models.
        """
        # OpenAIクライアントのモック作成
        # Create a mock for the OpenAI client
        mock_openai = MagicMock()
        mock_openai.responses.create.return_value = SimpleNamespace(output_text="openai-ok")

        with patch.object(llm, "openai_client", mock_openai):
            response = llm.get_llm_response(
                [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "hello"},
                ],
                llm.GPT_5_6_LUNA_MODEL,
            )

        # レスポンスおよび渡されたパラメータの検証
        # Assert the response and passed parameters
        self.assertEqual(response, "openai-ok")
        mock_openai.responses.create.assert_called_once()
        response_kwargs = mock_openai.responses.create.call_args.kwargs
        self.assertEqual(response_kwargs["model"], llm.GPT_5_6_LUNA_MODEL)
        self.assertEqual(response_kwargs["reasoning"], {"effort": "none"})
        passed_messages = response_kwargs["input"]
        self.assertEqual(passed_messages[0]["role"], "developer")
        self.assertTrue(
            passed_messages[0]["content"].startswith(f"{llm.OPENAI_MARKDOWN_REENABLE_PREFIX}\n")
        )

    def test_get_llm_response_rejects_invalid_model(self):
        """
        定義されていない無効なモデル名が指定された場合に、LlmInvalidModelErrorエラーが発生することを検証します。
        Verify that specifying an invalid model name raises an LlmInvalidModelError.
        """
        # エラー発生の検証
        # Assert error raises
        with self.assertRaises(llm.LlmInvalidModelError) as cm:
            llm.get_llm_response(
                [{"role": "user", "content": "hello"}],
                "invalid-model",
            )

        self.assertIn("無効なモデル", str(cm.exception))

    def test_get_llm_response_redacts_sensitive_values_before_provider_call(self):
        """
        プロバイダーにリクエストを送信する前に、APIキーなどの機密情報パターンがマスク（Redact）されることを検証します。
        Verify that sensitive patterns like API keys in messages are redacted before calling the provider API.
        """
        # 機密情報を含むメッセージを用意
        # Prepare a message containing sensitive API key pattern
        mock_groq = MagicMock()
        mock_groq.chat.completions.create.return_value = _mock_openai_response("ok")
        input_message = "api_key=sk-abcdefghijklmnopqrstuvwxyz012345"

        with patch.object(llm, "groq_client", mock_groq):
            response = llm.get_llm_response(
                [{"role": "user", "content": input_message}],
                llm.GROQ_MODEL,
            )

        # 送信されたメッセージの検証：機密情報がマスクされていること
        # Assert the message sent to the provider: the sensitive API key is masked
        self.assertEqual(response, "ok")
        passed_messages = mock_groq.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(len(passed_messages), 1)
        self.assertNotIn("sk-", passed_messages[0]["content"])
        self.assertIn("REDACTED-SENSITIVE", passed_messages[0]["content"])

    def test_get_groq_response_raises_configuration_error_without_api_key(self):
        """
        Groq APIキーが設定されていない（クライアントがNone）場合に、LlmConfigurationErrorが発生することを検証します。
        Verify that calling Groq API without an API key (client is None) raises an LlmConfigurationError.
        """
        with patch.object(llm, "groq_client", None):
            with self.assertRaises(llm.LlmConfigurationError):
                llm.get_groq_response(
                    [{"role": "user", "content": "hello"}],
                    llm.GROQ_MODEL,
                )

    def test_get_claude_response_wraps_provider_error_as_exception(self):
        """
        プロバイダー呼び出し時に例外が発生した場合、一般的なプロバイダーエラーとしてラップされることを検証します。
        Verify that raw runtime exceptions from Claude are wrapped as LlmProviderError.
        """
        mock_claude = MagicMock()
        mock_claude.messages.create.side_effect = RuntimeError("provider down")

        with patch.object(llm, "claude_client", mock_claude):
            with self.assertRaises(llm.LlmProviderError):
                llm.get_claude_response(
                    [{"role": "user", "content": "hello"}],
                    llm.CLAUDE_HAIKU_4_5_MODEL,
                )

    def test_get_claude_response_maps_rate_limit_error(self):
        """
        レートリミットエラーが発生した際、適切にリトライ可能なLlmRateLimitErrorにマップされることを検証します。
        Verify that RateLimitError from Claude is mapped to LlmRateLimitError (which is retryable).
        """
        # レートリミットエラー用のモッククラス
        # Mock class for RateLimitError
        class FakeRateLimitError(Exception):
            pass

        mock_claude = MagicMock()
        mock_claude.messages.create.side_effect = FakeRateLimitError("rate limit")

        with patch.object(llm, "AnthropicRateLimitError", FakeRateLimitError):
            with patch.object(llm, "claude_client", mock_claude):
                with self.assertRaises(llm.LlmRateLimitError) as cm:
                    llm.get_claude_response(
                        [{"role": "user", "content": "hello"}],
                        llm.CLAUDE_HAIKU_4_5_MODEL,
                    )

        # エラーがリトライ可能であるかの検証
        # Assert that the error is marked retryable
        self.assertTrue(llm.is_retryable_llm_error(cm.exception))

    def test_get_claude_response_maps_timeout_error(self):
        """
        タイムアウトエラーが発生した際、適切にリトライ可能なLlmTimeoutErrorにマップされることを検証します。
        Verify that APITimeoutError from Claude is mapped to LlmTimeoutError (which is retryable).
        """
        # タイムアウトエラー用のモッククラス
        # Mock class for APITimeoutError
        class FakeTimeoutError(Exception):
            pass

        mock_claude = MagicMock()
        mock_claude.messages.create.side_effect = FakeTimeoutError("timeout")

        with patch.object(llm, "AnthropicAPITimeoutError", FakeTimeoutError):
            with patch.object(llm, "claude_client", mock_claude):
                with self.assertRaises(llm.LlmTimeoutError) as cm:
                    llm.get_claude_response(
                        [{"role": "user", "content": "hello"}],
                        llm.CLAUDE_HAIKU_4_5_MODEL,
                    )

        # エラーがリトライ可能であるかの検証
        # Assert that the error is marked retryable
        self.assertTrue(llm.is_retryable_llm_error(cm.exception))

    def test_get_claude_response_maps_authentication_error(self):
        """
        認証エラーが発生した際、リトライ不可なLlmAuthenticationErrorにマップされることを検証します。
        Verify that AuthenticationError from Claude is mapped to LlmAuthenticationError (which is not retryable).
        """
        # 認証エラー用のモッククラス
        # Mock class for AuthenticationError
        class FakeAuthError(Exception):
            pass

        mock_claude = MagicMock()
        mock_claude.messages.create.side_effect = FakeAuthError("auth")

        with patch.object(llm, "AnthropicAuthenticationError", FakeAuthError):
            with patch.object(llm, "claude_client", mock_claude):
                with self.assertRaises(llm.LlmAuthenticationError) as cm:
                    llm.get_claude_response(
                        [{"role": "user", "content": "hello"}],
                        llm.CLAUDE_HAIKU_4_5_MODEL,
                    )

        # 認証エラーはリトライ不可であることを検証
        # Assert that the auth error is not marked retryable
        self.assertFalse(llm.is_retryable_llm_error(cm.exception))

    def test_get_openai_response_raises_configuration_error_without_api_key(self):
        """
        OpenAI APIキーが設定されていない場合に、LlmConfigurationErrorが発生することを検証します。
        Verify that calling OpenAI API without an API key raises an LlmConfigurationError.
        """
        with patch.object(llm, "openai_client", None):
            with self.assertRaises(llm.LlmConfigurationError):
                llm.get_openai_response(
                    [{"role": "user", "content": "hello"}],
                    llm.GPT_5_6_LUNA_MODEL,
                )

    def test_get_claude_response_stream_yields_chunks_and_closes_stream(self):
        """
        Claudeでのストリーミング出力時に、テキスト差分が順次出力され、最後にストリームがクローズされることを検証します。
        Verify that Claude streaming yields text deltas and closes the connection at the end.
        """
        mock_claude = MagicMock()
        mock_stream = _MockStream(
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="claude"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="-stream"),
            ),
        )
        mock_claude.messages.create.return_value = mock_stream

        with patch.object(llm, "claude_client", mock_claude):
            response = list(
                llm.get_claude_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.CLAUDE_HAIKU_4_5_MODEL,
                )
            )

        self.assertEqual(response, ["claude", "-stream"])
        self.assertTrue(mock_stream.closed)
        self.assertTrue(mock_claude.messages.create.call_args.kwargs["stream"])

    def test_get_claude_response_stream_raises_for_max_tokens(self):
        mock_claude = MagicMock()
        mock_stream = _MockStream(
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="partial"),
            ),
            SimpleNamespace(
                type="message_delta",
                delta=SimpleNamespace(stop_reason="max_tokens"),
            ),
        )
        mock_claude.messages.create.return_value = mock_stream

        with patch.object(llm, "claude_client", mock_claude):
            stream = llm.get_claude_response_stream(
                [{"role": "user", "content": "hello"}],
                llm.CLAUDE_HAIKU_4_5_MODEL,
            )
            self.assertEqual(next(stream), "partial")
            with self.assertRaises(llm.LlmOutputLimitError):
                next(stream)

        self.assertTrue(mock_stream.closed)

    def test_get_claude_response_stream_converts_function_tools(self):
        """
        OpenAI形式の関数ツールがClaude形式へ変換されることを検証します。
        Verify that OpenAI function tools are converted to Claude tool definitions.
        """
        mock_claude = MagicMock()
        mock_stream = _MockStream()
        mock_claude.messages.create.return_value = mock_stream
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        with patch.object(llm, "claude_client", mock_claude):
            response = list(
                llm.get_claude_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.CLAUDE_HAIKU_4_5_MODEL,
                    tools=tools,
                )
            )

        self.assertEqual(response, [])
        request_kwargs = mock_claude.messages.create.call_args.kwargs
        self.assertEqual(
            request_kwargs["tools"],
            [
                {
                    "name": "web_search",
                    "description": "Search the web.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        )

    def test_get_groq_response_stream_yields_chunks_and_closes_stream(self):
        """
        Groqでのストリーミング出力時に、テキスト差分が順次出力され、最後にストリームがクローズされることを検証します。
        Verify that Groq streaming yields text deltas and closes the connection at the end.
        """
        mock_groq = MagicMock()
        mock_stream = _MockStream(
            _mock_stream_chunk("groq"),
            _mock_stream_chunk(None),
            _mock_stream_chunk("-stream"),
        )
        mock_groq.chat.completions.create.return_value = mock_stream

        with patch.object(llm, "groq_client", mock_groq):
            response = list(
                llm.get_groq_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.GROQ_MODEL,
                )
            )

        # 差分テキストの検証およびストリームの終了の検証
        # Assert that text deltas are correctly output and the stream is closed
        self.assertEqual(response, ["groq", "-stream"])
        self.assertTrue(mock_stream.closed)
        request_kwargs = mock_groq.chat.completions.create.call_args.kwargs
        self.assertTrue(request_kwargs["stream"])
        self.assertFalse(request_kwargs["extra_body"]["include_reasoning"])
        self.assertNotIn("reasoning_effort", request_kwargs["extra_body"])

    def test_get_groq_response_stream_raises_after_yielding_token_limited_text(self):
        mock_groq = MagicMock()
        mock_stream = _MockStream(
            _mock_stream_chunk("partial"),
            _mock_stream_chunk(None, finish_reason="length"),
        )
        mock_groq.chat.completions.create.return_value = mock_stream

        with patch.object(llm, "groq_client", mock_groq):
            stream = llm.get_groq_response_stream(
                [{"role": "user", "content": "hello"}],
                llm.GROQ_MODEL,
            )
            self.assertEqual(next(stream), "partial")
            with self.assertRaises(llm.LlmOutputLimitError):
                next(stream)

        self.assertTrue(mock_stream.closed)

    def test_get_qwen_response_stream_hides_reasoning_without_disabling_it(self):
        mock_groq = MagicMock()
        mock_stream = _MockStream(_mock_stream_chunk("qwen-stream"))
        mock_groq.chat.completions.create.return_value = mock_stream

        with patch.object(llm, "groq_client", mock_groq):
            response = list(
                llm.get_groq_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.QWEN_3_6_27B_MODEL,
                )
            )

        self.assertEqual(response, ["qwen-stream"])
        request_kwargs = mock_groq.chat.completions.create.call_args.kwargs
        self.assertEqual(request_kwargs["extra_body"]["reasoning_effort"], "default")
        self.assertEqual(request_kwargs["extra_body"]["reasoning_format"], "hidden")
        self.assertNotIn("include_reasoning", request_kwargs["extra_body"])
        self.assertTrue(mock_stream.closed)

    def test_final_answer_phase_reduces_groq_reasoning_budget(self):
        mock_groq = MagicMock()
        mock_groq.chat.completions.create.return_value = _MockStream(
            _mock_stream_chunk("answer")
        )

        with patch.object(llm, "groq_client", mock_groq):
            list(
                llm.get_groq_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.GROQ_MODEL,
                    generation_phase="final_answer",
                )
            )

        extra_body = mock_groq.chat.completions.create.call_args.kwargs["extra_body"]
        self.assertEqual(extra_body["reasoning_effort"], "low")
        self.assertEqual(extra_body["reasoning_format"], "hidden")

    def test_get_groq_response_stream_aggregates_tool_call_chunks(self):
        """
        Groqストリーミング内で複数のツール呼び出しのチャンク（引数分割など）が適切に集約され、JSON文字列として出力されることを検証します。
        Verify that tool call chunks (with split arguments) are aggregated and yielded as a single JSON string in Groq stream.
        """
        mock_groq = MagicMock()
        # ツール呼び出しが引数単位で分割されて配信される状況を模ック
        # Mock tool call parts delivered in multiple chunks
        mock_stream = _MockStream(
            _mock_tool_call_chunk(
                call_id="call-1",
                name="web_search",
                arguments='{"query": ',
            ),
            _mock_tool_call_chunk(arguments='"OpenAI latest news"}'),
        )
        mock_groq.chat.completions.create.return_value = mock_stream

        with patch.object(llm, "groq_client", mock_groq):
            response = list(
                llm.get_groq_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.GROQ_MODEL,
                    tools=[{"type": "function", "function": {"name": "web_search"}}],
                )
            )

        # 集約されたJSONデータの検証
        # Assert the aggregated JSON tool call content
        tool_calls = json.loads(response[0])
        self.assertEqual(tool_calls[0]["id"], "call-1")
        self.assertEqual(tool_calls[0]["function"]["name"], "web_search")
        self.assertEqual(
            json.loads(tool_calls[0]["function"]["arguments"]),
            {"query": "OpenAI latest news"},
        )
        self.assertTrue(mock_stream.closed)

    def test_get_llm_response_stream_routes_to_groq(self):
        """
        ストリーミング共通APIへモデル名としてGroqモデルを渡した際、Groq用ストリーム関数へ適切に処理が委譲されることを検証します。
        Verify that calls to get_llm_response_stream are routed to the Groq stream helper when a Groq model is used.
        """
        messages = [{"role": "user", "content": "hello"}]
        tools = [{"type": "function", "function": {"name": "web_search"}}]
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

        # 呼び出し結果およびパラメータの検証
        # Assert the output and call arguments
        self.assertEqual(response, ["groq", "-stream"])
        mock_stream.assert_called_once_with(messages, llm.GROQ_MODEL, tools=tools)

    def test_get_openai_response_stream_yields_text_deltas(self):
        """
        OpenAIのレスポンスAPIを用いたストリーミング時に、差分テキストが正しく抽出・出力されることを検証します。
        Verify that OpenAI responses.stream correctly yields text deltas.
        """
        # ストリーミングイベントのモックを作成
        # Mock streaming events
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

        with patch.object(llm, "openai_client", mock_openai):
            response = list(
                llm.get_openai_response_stream(
                    [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "hello"},
                    ],
                    llm.GPT_5_6_LUNA_MODEL,
                )
            )

        # レスポンスおよびパラメータ変換の検証
        # Assert the response and input parameter translation
        self.assertEqual(response, ["openai", "-stream"])
        mock_openai.responses.stream.assert_called_once()
        stream_kwargs = mock_openai.responses.stream.call_args.kwargs
        self.assertEqual(stream_kwargs["reasoning"], {"effort": "none"})
        passed_messages = stream_kwargs["input"]
        self.assertEqual(passed_messages[0]["role"], "developer")
        self.assertTrue(
            passed_messages[0]["content"].startswith(f"{llm.OPENAI_MARKDOWN_REENABLE_PREFIX}\n")
        )

    def test_get_openai_response_stream_raises_for_max_output_tokens(self):
        mock_openai = MagicMock()
        delta_event = SimpleNamespace(
            type="response.output_text.delta",
            delta="partial",
        )
        incomplete_event = SimpleNamespace(
            type="response.incomplete",
            response=SimpleNamespace(
                incomplete_details=SimpleNamespace(reason="max_output_tokens")
            ),
        )
        mock_stream = MagicMock()
        mock_stream.__iter__ = MagicMock(
            return_value=iter([delta_event, incomplete_event])
        )
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__enter__.return_value = mock_stream
        mock_stream_ctx.__exit__.return_value = None
        mock_openai.responses.stream.return_value = mock_stream_ctx

        with patch.object(llm, "openai_client", mock_openai):
            stream = llm.get_openai_response_stream(
                [{"role": "user", "content": "hello"}],
                llm.GPT_5_6_LUNA_MODEL,
            )
            self.assertEqual(next(stream), "partial")
            with self.assertRaises(llm.LlmOutputLimitError):
                next(stream)

    def test_get_openai_response_stream_with_tools_uses_chat_completions_stream(self):
        """
        ツール呼び出しを伴うOpenAIストリーミングの場合、レスポンスAPIではなく従来のチャットコンプリーションのストリームが利用されることを検証します。
        Verify that OpenAI streaming falls back to chat.completions.create stream when tools are defined.
        """
        mock_openai = MagicMock()
        mock_stream = _MockStream(_mock_stream_chunk("tool"), _mock_stream_chunk("-stream"))
        mock_openai.chat.completions.create.return_value = mock_stream

        with patch.object(llm, "openai_client", mock_openai):
            response = list(
                llm.get_openai_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.GPT_5_6_LUNA_MODEL,
                    tools=[{"type": "function", "function": {"name": "web_search"}}],
                )
            )

        # chat.completions.create が呼ばれ、かつ responses.stream が呼ばれていないことを検証
        # Verify that chat.completions.create is called and responses.stream is not
        self.assertEqual(response, ["tool", "-stream"])
        mock_openai.chat.completions.create.assert_called_once()
        chat_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        self.assertEqual(chat_kwargs["max_completion_tokens"], llm.LLM_MAX_TOKENS)
        self.assertNotIn("max_tokens", chat_kwargs)
        self.assertEqual(chat_kwargs["reasoning_effort"], "none")
        self.assertEqual(chat_kwargs["tool_choice"], "auto")
        mock_openai.responses.stream.assert_not_called()
        self.assertTrue(mock_stream.closed)

    def test_get_openai_response_stream_with_tool_history_uses_chat_completions(self):
        """
        メッセージ履歴の中にツール呼び出し履歴（tool/assistant role）が含まれている場合、OpenAI responses APIではなく従来のチャットコンプリーションが利用されることを検証します。
        Verify that OpenAI streaming falls back to chat.completions.create stream when messages contain tool invocation history.
        """
        mock_openai = MagicMock()
        mock_stream = _MockStream(_mock_stream_chunk("final"))
        mock_openai.chat.completions.create.return_value = mock_stream

        # 過去のツール呼び出し履歴を含むメッセージ
        # Message history including tool and assistant roles
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

        with patch.object(llm, "openai_client", mock_openai):
            response = list(llm.get_openai_response_stream(messages, llm.GPT_5_6_LUNA_MODEL))

        # 履歴が存在するため、chat.completions.create がフォールバックされることを検証
        # Verify fallback to chat.completions.create due to tool history
        self.assertEqual(response, ["final"])
        mock_openai.chat.completions.create.assert_called_once()
        chat_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        self.assertNotIn("tools", chat_kwargs)
        self.assertNotIn("tool_choice", chat_kwargs)
        self.assertEqual(chat_kwargs["reasoning_effort"], "none")
        mock_openai.responses.stream.assert_not_called()
        self.assertTrue(mock_stream.closed)

    def test_get_llm_response_stream_routes_to_openai(self):
        """
        ストリーミング共通APIへモデル名としてOpenAIモデルを渡した際、OpenAI用ストリーム関数へ適切に処理が委譲されることを検証します。
        Verify that calls to get_llm_response_stream are routed to the OpenAI stream helper when an OpenAI model is used.
        """
        with patch.object(
            llm,
            "get_openai_response_stream",
            return_value=iter(["openai", "-stream"]),
        ) as mock_stream:
            response = list(
                llm.get_llm_response_stream(
                    [{"role": "user", "content": "hello"}],
                    llm.GPT_5_6_LUNA_MODEL,
                )
            )

        # 呼び出しのルーティングを検証
        # Assert the routed stream call
        self.assertEqual(response, ["openai", "-stream"])
        mock_stream.assert_called_once()


if __name__ == "__main__":
    # テストを実行します
    # Execute the tests
    unittest.main()
