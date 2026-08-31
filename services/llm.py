# 複数のプロバイダに対応したOpenAIクライアントを利用するLLMサービスモジュールです。
# LLM service module using OpenAI client for multiple providers.

import json
import logging
import os
import re
from collections.abc import Iterator
from typing import Any

from anthropic import Anthropic
from anthropic import (
    APIConnectionError as AnthropicAPIConnectionError,
    APIStatusError as AnthropicAPIStatusError,
    APITimeoutError as AnthropicAPITimeoutError,
    AuthenticationError as AnthropicAuthenticationError,
    RateLimitError as AnthropicRateLimitError,
)
from openai import OpenAI
try:
    from openai import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        AuthenticationError,
        RateLimitError,
    )
except ImportError:  # pragma: no cover - depends on SDK version
    # OpenAI SDKの例外クラスが存在しない（インポートできない）場合のダミー例外クラスです。
    # Dummy exception class used when OpenAI SDK exception classes are not available for import.
    class _UnavailableOpenAIError(Exception):
        pass

    APIConnectionError = _UnavailableOpenAIError  # type: ignore[assignment]
    APIStatusError = _UnavailableOpenAIError  # type: ignore[assignment]
    APITimeoutError = _UnavailableOpenAIError  # type: ignore[assignment]
    AuthenticationError = _UnavailableOpenAIError  # type: ignore[assignment]
    RateLimitError = _UnavailableOpenAIError  # type: ignore[assignment]


# 環境変数から正の整数値を取得します。無効な場合はデフォルト値を返します。
# Retrieve a positive integer from environment variables, returning the default if invalid.
def _get_positive_int_env(name: str, default: int) -> int:
    # 正の整数のみ採用し、無効値は安全側で既定値へ戻します。
    # Accept only positive integers and fallback to default on invalid values.
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# 環境変数から0以上の整数値を取得します。無効な場合はデフォルト値を返します。
# Retrieve a non-negative integer from environment variables, returning the default if invalid.
def _get_non_negative_int_env(name: str, default: int) -> int:
    # 0以上の整数を採用し、無効値は既定値へ戻します（再試行回数などで0を許容します）。
    # Accept zero or positive integers (e.g. retry counts) and fallback on invalid values.
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


GPT_OSS_120B_MODEL = "openai/gpt-oss-120b"
GPT_OSS_20B_MODEL = "openai/gpt-oss-20b"
# 軽量な補助タスクは会話で選択されたモデルに依存させず、Groq の20Bへ固定する。
# Keep lightweight auxiliary tasks independent from the chat model selected by the user.
LIGHTWEIGHT_TASK_MODEL = GPT_OSS_20B_MODEL
QWEN_3_6_27B_MODEL = "qwen/qwen3.6-27b"
GPT_5_6_LUNA_MODEL = "gpt-5.6-luna"
CLAUDE_HAIKU_4_5_MODEL = "claude-haiku-4-5-20251001"
GPT_OSS_MODELS = {GPT_OSS_20B_MODEL, GPT_OSS_120B_MODEL}
GROQ_MODEL = GPT_OSS_120B_MODEL
OPENAI_DEFAULT_MODEL = GPT_5_6_LUNA_MODEL
CLAUDE_DEFAULT_MODEL = CLAUDE_HAIKU_4_5_MODEL
# 対応モデル（Claude Haiku / gpt-oss / Qwen / gpt-5.6-luna）はいずれも思考トークンがこの上限に
# 含まれる。4096では生成UI（最大8000文字のコード）＋思考で頻繁に途中打ち切りが発生する
# ため、既定値を引き上げる（全プロバイダの出力上限 65536 以内）。
# All supported models (Claude Haiku / gpt-oss / Qwen / gpt-5.6-luna) count reasoning tokens
# against this cap. 4096 frequently truncated generative UI output (up to ~8000 chars of
# code) mid-stream, so raise the default (well within every provider's 65536 output cap).
LLM_MAX_TOKENS = _get_positive_int_env("LLM_MAX_TOKENS", 16384)
# 出力枠はフェーズごとに分ける。単一の上限を全フェーズで共有すると、調査ステップに
# 過剰な枠を与えたまま、本文を書く最終回答フェーズが足りなくなる。
# フェーズ別の値は LLM_MAX_TOKENS から派生させない。運用環境が古い LLM_MAX_TOKENS
# （例: 4096）を残していても、本文を書くフェーズが道連れで枯渇しないようにするため。
# Split the output budget by phase. One shared cap over-provisions research steps while
# starving the phase that actually writes the answer. The per-phase values deliberately do
# not derive from LLM_MAX_TOKENS so that a stale deployment value cannot starve the answer.
# 調査ステップが書くのはツール呼び出しと1〜2文の内部ノートだけなので、枠は小さくてよい。
# A research step only emits tool calls and a one-or-two sentence internal note.
LLM_RESEARCH_MAX_TOKENS = _get_positive_int_env("LLM_MAX_TOKENS_RESEARCH", 8192)
# 最終回答と継続は本文そのものを書く。長い調査の後でも1パスで書き切れる枠を確保する。
# The final answer and its continuations write the body itself, so they need room to finish
# a long research answer in a single pass.
LLM_ANSWER_MAX_TOKENS = _get_positive_int_env("LLM_MAX_TOKENS_ANSWER", 32768)

# 調査（ツール選択）フェーズと、本文を書く回答フェーズを名前で区別する。
# Distinguish the tool-selecting research phases from the answer-writing phases by name.
RESEARCH_GENERATION_PHASES = frozenset({"research", "research_wrapup"})
ANSWER_GENERATION_PHASES = frozenset(
    {"final_answer", "continuation", "final_answer_deep", "continuation_deep"}
)
# 調査を伴うターンの回答フェーズ。長い調査の後の統合は、そのターンで最も難しい作業なので、
# 思考量を最小に落としたままにしない。調査のない雑談は従来どおり低遅延を優先する。
# The answer phase of a turn that did research. Synthesising after a long research phase is
# the hardest work in the turn, so it must not run on the smallest reasoning budget; a turn
# with no research keeps the low-latency baseline.
DEEP_REASONING_PHASES = frozenset({"final_answer_deep", "continuation_deep"})


# 生成フェーズに応じた出力トークン上限を返す
# Return the output-token cap that applies to a generation phase.
def max_output_tokens_for_phase(generation_phase: str = "default") -> int:
    if generation_phase in ANSWER_GENERATION_PHASES:
        return LLM_ANSWER_MAX_TOKENS
    if generation_phase in RESEARCH_GENERATION_PHASES:
        return LLM_RESEARCH_MAX_TOKENS
    return LLM_MAX_TOKENS
LLM_REQUEST_TIMEOUT_SECONDS = 30.0
# 一時的な接続失敗を吸収するため既定の再試行回数を増やします（環境変数で調整可能です）。
# Retry transient connection failures by default; configurable via env var.
LLM_MAX_RETRIES = _get_non_negative_int_env("LLM_MAX_RETRIES", 2)

REDACTED_SENSITIVE_VALUE = "[REDACTED-SENSITIVE]"
OPENAI_MARKDOWN_REENABLE_PREFIX = "Formatting re-enabled"
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----",
        re.IGNORECASE,
    ),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
)
_SENSITIVE_ASSIGNMENT_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*([^\s,;]+)"
    ),
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# サポート対象モデルを明示し、入力バリデーションの単一情報源にする
# Keep supported model names explicit as the single validation source.
# Valid model names
VALID_CLAUDE_MODELS = {CLAUDE_DEFAULT_MODEL, CLAUDE_HAIKU_4_5_MODEL}
VALID_GROQ_MODELS = {
    GROQ_MODEL,
    GPT_OSS_120B_MODEL,
    GPT_OSS_20B_MODEL,
    QWEN_3_6_27B_MODEL,
}
VALID_OPENAI_MODELS = {
    OPENAI_DEFAULT_MODEL,
    GPT_5_6_LUNA_MODEL,
}

groq_api_key = os.environ.get("GROQ_API_KEY", "")
anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
openai_api_key = os.environ.get("OPENAI_API_KEY", "")

# APIキーがある場合のみクライアントを構築し、未設定時は None を保持する
# Initialize provider clients only when corresponding API keys are present.
groq_client = (
    OpenAI(
        api_key=groq_api_key,
        base_url=GROQ_BASE_URL,
        timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )
    if groq_api_key
    else None
)
claude_client = (
    Anthropic(
        api_key=anthropic_api_key,
        timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )
    if anthropic_api_key
    else None
)
openai_client = (
    OpenAI(
        api_key=openai_api_key,
        timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )
    if openai_api_key
    else None
)
logger = logging.getLogger(__name__)
ConversationMessages = list[dict[str, Any]]


# LLMサービス全体に関する基本例外クラス。
# Base exception class for LLM service-related errors.
class LlmServiceError(RuntimeError):
    # LLM連携で発生する例外の基底クラス
    # Base exception class for LLM integration failures.
    pass


# LLMサービスの設定不備に関する例外クラス。
# Exception class for LLM service configuration errors.
class LlmConfigurationError(LlmServiceError):
    # APIキー未設定など、設定不備に関する例外
    # Configuration-related exception (e.g., missing API key).
    pass


# LLMプロバイダ呼び出しエラーに関する例外クラス。
# Exception class for LLM provider invocation errors.
class LlmProviderError(LlmServiceError):
    # 外部プロバイダ呼び出し失敗に関する例外
    # Provider-call failure exception.
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


# 再試行可能なLLMプロバイダエラーに関する例外クラス。
# Exception class for retryable LLM provider errors.
class LlmRetryableProviderError(LlmProviderError):
    # 再試行により回復可能な可能性が高いプロバイダ例外
    # Provider-call failure that is likely retryable.
    retryable = True


class LlmOutputLimitError(LlmServiceError):
    """The provider ended a valid stream because its output budget was exhausted."""

    def __init__(self, message: str, *, reason: str = "output_limit") -> None:
        super().__init__(message)
        self.reason = reason


class LlmInputLimitError(LlmServiceError):
    """The provider rejected the request because the input exceeded its context window.

    これは出力上限とは回復方法が正反対である。出力上限は「続きを生成」で回復できるが、
    入力超過で続きを渡すと入力がさらに増えて必ず再失敗する。回復は入力の圧縮だけ。
    Recovery is the opposite of an output limit: continuing an output-limited answer works,
    but feeding the partial answer back after an input overflow only grows the request and
    fails again. The only recovery is to shrink the input.
    """

    def __init__(self, message: str, *, reason: str = "input_limit") -> None:
        super().__init__(message)
        self.reason = reason


# レート制限によるLLMプロバイダエラーに関する例外クラス。
# Exception class for LLM provider rate limit errors.
class LlmRateLimitError(LlmRetryableProviderError):
    # レート制限による失敗
    # Provider rate-limit failure.
    pass


# タイムアウトによるLLMプロバイダエラーに関する例外クラス。
# Exception class for LLM provider timeout errors.
class LlmTimeoutError(LlmRetryableProviderError):
    # タイムアウトによる失敗
    # Provider timeout failure.
    pass


# ネットワークエラーによるLLMプロバイダエラーに関する例外クラス。
# Exception class for LLM provider network errors.
class LlmNetworkError(LlmRetryableProviderError):
    # ネットワーク到達性による失敗
    # Provider network/connectivity failure.
    pass


# 上流サービスのエラーによるLLMプロバイダエラーに関する例外クラス。
# Exception class for LLM provider upstream service errors.
class LlmUpstreamServiceError(LlmRetryableProviderError):
    # 上流サービス障害 (5xx)
    # Upstream provider service failure (5xx).
    pass


# 認証エラーによるLLMプロバイダエラーに関する例外クラス。
# Exception class for LLM provider authentication errors.
class LlmAuthenticationError(LlmProviderError):
    # 認証・権限不備による失敗
    # Provider authentication/authorization failure.
    pass


# 指定されたモデルが無効である場合の例外クラス。
# Exception class for invalid LLM model specifications.
class LlmInvalidModelError(LlmServiceError):
    # 未サポートモデル指定時の例外
    # Unsupported model selection exception.
    pass


# 与えられた例外がLLMプロバイダの一時的なエラー（再試行可能）かどうかを判定する
# Determine whether the given exception is a transient/retryable LLM provider error.
# 与えられた例外が再試行可能なLLMプロバイダエラーかどうかを判定します。
# Check whether the given exception is a retryable LLM provider error.
def is_retryable_llm_error(exc: BaseException) -> bool:
    return isinstance(exc, LlmRetryableProviderError)


# HTTPレスポンスヘッダからRetry-After秒数を抽出する
# Extract the Retry-After value (in seconds) from the HTTP response headers.
# HTTPレスポンスヘッダーからRetry-Afterの値を抽出し、秒数に変換します。
# Extract the Retry-After value from HTTP response headers and convert it to seconds.
def _extract_retry_after_seconds(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    raw_retry_after = headers.get("retry-after")
    if raw_retry_after is None:
        return None
    try:
        retry_after = int(str(raw_retry_after).strip())
    except (TypeError, ValueError):
        return None
    return retry_after if retry_after >= 0 else None


# プロバイダが返す「入力（コンテキスト長）超過」を、文面と本文から判別する。
# 各プロバイダで文言もエラーコードも異なるため、既知の表現をまとめて照合する。
# Detect a provider's input/context-length overflow from its message and body. The wording
# and error codes differ per provider, so match the known phrasings together.
_INPUT_LIMIT_ERROR_PATTERN = re.compile(
    r"context[_ ]length|context[_ ]window|maximum context|too many (?:input )?tokens|"
    r"input (?:is )?too long|prompt (?:is )?too long|reduce the length of the messages|"
    r"request too large|exceeds the (?:model|maximum) context",
    re.IGNORECASE,
)


def _looks_like_input_limit_error(exc: BaseException) -> bool:
    candidates: list[str] = [str(exc)]
    for attribute in ("message", "code", "body"):
        value = getattr(exc, attribute, None)
        if value is not None:
            candidates.append(str(value))
    return any(
        _INPUT_LIMIT_ERROR_PATTERN.search(candidate)
        for candidate in candidates
        if candidate
    )


# 外部OpenAI/Groq/Claudeクライアントの例外をアプリケーション独自のLlmProviderError派生例外にマッピングする
# Map raw exceptions from OpenAI/Groq/Claude SDKs to application-specific LlmProviderError sub-classes.
# LLMプロバイダSDK独自の例外を、アプリケーション共通のLLM例外にマッピングします。
# Map provider-specific exceptions to application-specific LLM exceptions.
def _map_provider_exception(
    exc: BaseException,
    *,
    provider_name: str,
    fallback_message: str,
) -> LlmServiceError:
    if isinstance(exc, LlmServiceError):
        return exc

    if isinstance(exc, (RateLimitError, AnthropicRateLimitError)):
        return LlmRateLimitError(
            f"{provider_name} API rate limit exceeded.",
            retry_after_seconds=_extract_retry_after_seconds(exc),
        )
    if isinstance(exc, (APITimeoutError, AnthropicAPITimeoutError)):
        return LlmTimeoutError(f"{provider_name} API request timed out.")
    if isinstance(exc, (APIConnectionError, AnthropicAPIConnectionError)):
        return LlmNetworkError(f"{provider_name} API connection failed.")
    if isinstance(exc, (AuthenticationError, AnthropicAuthenticationError)):
        return LlmAuthenticationError(f"{provider_name} API authentication failed.")
    if isinstance(exc, (APIStatusError, AnthropicAPIStatusError)):
        status_code = getattr(exc, "status_code", None)
        if status_code in (401, 403):
            return LlmAuthenticationError(f"{provider_name} API authentication failed.")
        if status_code == 408:
            return LlmTimeoutError(f"{provider_name} API request timed out.")
        if status_code == 429:
            return LlmRateLimitError(
                f"{provider_name} API rate limit exceeded.",
                retry_after_seconds=_extract_retry_after_seconds(exc),
            )
        if isinstance(status_code, int) and status_code >= 500:
            return LlmUpstreamServiceError(f"{provider_name} API is temporarily unavailable.")
        # 入力超過は 400／413 で返る。再試行しても同じ入力では必ず失敗するため、
        # 一時障害ではなく入力側の問題として分類する。
        # Input overflow arrives as 400/413. Retrying the same input always fails again, so
        # classify it as an input problem rather than a transient provider failure.
        if status_code in (400, 413) and _looks_like_input_limit_error(exc):
            return LlmInputLimitError(
                f"{provider_name} API rejected the request: input exceeds the context window."
            )

    if _looks_like_input_limit_error(exc):
        return LlmInputLimitError(
            f"{provider_name} API rejected the request: input exceeds the context window."
        )
    return LlmProviderError(fallback_message)


# マッピングされたLLMプロバイダエラーをログ出力し、例外として発生させる
# Log and raise the mapped LLM provider error.
# LLMプロバイダ例外を共通例外に変換してログ出力し、送出します。
# Map the LLM provider exception, log it, and raise it.
def _raise_provider_error(
    exc: BaseException,
    *,
    provider_name: str,
    fallback_message: str,
) -> None:
    mapped_error = _map_provider_exception(
        exc,
        provider_name=provider_name,
        fallback_message=fallback_message,
    )
    logger.error(
        "%s (%s -> %s).",
        fallback_message,
        exc.__class__.__name__,
        mapped_error.__class__.__name__,
    )
    raise mapped_error from exc


# 指定されたLLMモデルが無効であることを警告し、例外を発生させる
# Log a warning for an invalid LLM model name and raise a LlmInvalidModelError.
# 無効なモデルが指定された場合のエラーログを出力し、例外を送出します。
# Log an error message and raise a LlmInvalidModelError for an invalid model name.
def _raise_invalid_model_error(model_name: str) -> None:
    valid_models = sorted(VALID_CLAUDE_MODELS | VALID_GROQ_MODELS | VALID_OPENAI_MODELS)
    logger.warning(
        "Invalid model requested: %s. Valid models: %s",
        model_name,
        valid_models,
    )
    raise LlmInvalidModelError(
        f"無効なモデル '{model_name}' が指定されました。"
        f"有効なモデル: {', '.join(valid_models)}"
    )


# モデルの種類に応じて最大トークン数指定のキーを設定する（OpenAIの場合はmax_completion_tokens）
# Resolve parameter name and value for limiting output tokens based on the model (e.g. max_completion_tokens for OpenAI).
# モデルファミリーに合わせて、最大トークン数制限を指定する引数辞書を構築します。
# Construct the keyword arguments dictionary for max token limits based on the model family.
def _chat_completion_token_limit_kwargs(
    model_name: str,
    *,
    generation_phase: str = "default",
) -> dict[str, int]:
    max_tokens = max_output_tokens_for_phase(generation_phase)
    if is_openai_model(model_name):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


def _openai_reasoning_kwargs(model_name: str) -> dict[str, Any]:
    """Preserve GPT-5 mini's low-latency baseline for GPT-5.6 Luna requests."""
    if model_name == GPT_5_6_LUNA_MODEL:
        return {"reasoning_effort": "none"}
    return {}


def _openai_responses_reasoning_kwargs(model_name: str) -> dict[str, Any]:
    """Use the Responses API equivalent of the GPT-5.6 Luna reasoning baseline."""
    if model_name == GPT_5_6_LUNA_MODEL:
        return {"reasoning": {"effort": "none"}}
    return {}


def _groq_reasoning_kwargs(
    model_name: str,
    *,
    generation_phase: str = "default",
) -> dict[str, Any]:
    """Return Groq-only reasoning options through the OpenAI SDK extension body."""
    reasoning_options: dict[str, Any] = {}
    is_answer_phase = generation_phase in ANSWER_GENERATION_PHASES
    is_deep_phase = generation_phase in DEEP_REASONING_PHASES
    if model_name == QWEN_3_6_27B_MODEL:
        reasoning_options = {
            "reasoning_effort": "none" if (is_answer_phase and not is_deep_phase) else "default",
            "reasoning_format": "hidden",
        }
    elif model_name in GPT_OSS_MODELS:
        if is_answer_phase:
            reasoning_options = {
                "reasoning_effort": "medium" if is_deep_phase else "low",
                "reasoning_format": "hidden",
            }
        elif generation_phase in RESEARCH_GENERATION_PHASES:
            reasoning_options = {
                "reasoning_effort": "medium",
                "reasoning_format": "hidden",
            }
        else:
            reasoning_options = {"include_reasoning": False}

    # The application uses the OpenAI SDK against Groq's compatible endpoint.
    # Groq-specific fields are not accepted as top-level SDK keyword arguments,
    # so pass them through its supported extension body instead.
    return {"extra_body": reasoning_options} if reasoning_options else {}


# ツール呼び出しの設定用キーワード引数を構築する
# Build tool-choice keyword arguments for chat completions.
# LLMツール（関数呼び出し）指定用の引数辞書を構築します。
# Construct the keyword arguments dictionary for tool specification.
def _chat_completion_tool_kwargs(
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if not tools:
        return {}
    return {
        "tools": tools,
        "tool_choice": "auto",
    }


# 会話履歴にツール（関数呼び出し）の履歴が含まれているかチェックする
# Check if the conversation messages history contains tool-call results or requests.
# 会話履歴にツール（関数呼び出し）の呼び出しや結果が含まれているか判定します。
# Check whether the conversation history contains tool calls or tool response messages.
def _conversation_has_tool_history(conversation_messages: ConversationMessages) -> bool:
    for message in conversation_messages:
        role = str(message.get("role", ""))
        if role == "tool":
            return True
        if message.get("tool_calls"):
            return True
    return False


# テキスト内にあるAPIキーやパスワードなどの機密情報を伏せ字にする
# Redact sensitive information (API keys, passwords) from the given text.
# テキスト中のAPIキーやシークレットなどの機密情報をマスクします。
# Redact sensitive information (API keys, secrets) found in the text.
def _redact_sensitive_text(value: str) -> str:
    # 既知トークン形式と key=value 形式の両方を伏せ字化する
    # Redact both known token patterns and key=value style secrets.
    redacted = value
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub(REDACTED_SENSITIVE_VALUE, redacted)
    for pattern in _SENSITIVE_ASSIGNMENT_PATTERNS:
        redacted = pattern.sub(r"\1=<REDACTED-SENSITIVE>", redacted)
    return redacted


# 会話メッセージ履歴内のすべての機密情報（APIキー等）をマスク処理する
# Redact sensitive information from all conversation messages in the history.
# 会話履歴メッセージから機密情報を一括してマスク処理します。
# Sanitize and redact sensitive information from all conversation messages.
def _sanitize_conversation_messages(
    conversation_messages: ConversationMessages,
) -> ConversationMessages:
    sanitized_messages: ConversationMessages = []
    redacted_message_count = 0

    for message in conversation_messages:
        new_msg = dict(message)
        role = str(new_msg.get("role", "user"))
        raw_content = new_msg.get("content")
        
        if raw_content is None:
            content = None
            redacted_content = None
        else:
            content = raw_content if isinstance(raw_content, str) else str(raw_content)
            redacted_content = _redact_sensitive_text(content)
            if redacted_content != content:
                redacted_message_count += 1
        
        new_msg["role"] = role
        new_msg["content"] = redacted_content
        sanitized_messages.append(new_msg)

    if redacted_message_count > 0:
        logger.warning(
            "Redacted sensitive content in %s message(s) before LLM request.",
            redacted_message_count,
        )
    return sanitized_messages


# OpenAI Responses APIのインプット用に、ロール名を developer に変換し、Markdownフォーマットの有効化を行います。
# Prepare input messages for OpenAI Responses API by converting system role to developer and enabling markdown support.
def _prepare_openai_responses_input(
    conversation_messages: ConversationMessages,
) -> ConversationMessages:
    prepared_messages: ConversationMessages = []
    markdown_reenabled = False

    for message in conversation_messages:
        new_msg = dict(message)
        role = str(new_msg.get("role", "user"))
        raw_content = new_msg.get("content")
        
        if raw_content is None:
            normalized_content = None
        else:
            normalized_content = raw_content if isinstance(raw_content, str) else str(raw_content)

        if role == "system":
            # Responses API では従来の system 相当を developer として渡します。先頭の developer message に Markdown を明示的に許可し、通常回答の装飾が失われないようにします。
            # Pass the legacy system messages as developer messages in the Responses API. Explicitly enable Markdown for the leading developer message to preserve formatting.
            role = "developer"
            if normalized_content is not None and not markdown_reenabled:
                stripped_content = normalized_content.lstrip()
                if not stripped_content.startswith(OPENAI_MARKDOWN_REENABLE_PREFIX):
                    normalized_content = (
                        f"{OPENAI_MARKDOWN_REENABLE_PREFIX}\n{normalized_content}"
                    )
                markdown_reenabled = True

        new_msg["role"] = role
        new_msg["content"] = normalized_content
        prepared_messages.append(new_msg)

    return prepared_messages


# Groq APIを呼び出してモデルからのテキスト応答または関数呼び出しデータを取得する
# Call the Groq API to retrieve text responses or function-call details.
# Groq APIを呼び出して応答を取得します（ツール定義がある場合は関数呼び出しデータを含むJSONを返すことがあります）。
# Call the Groq API to retrieve the response (may return a JSON string for tool calls if tools are provided).
def get_groq_response(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> str | None:
    # Groq 向けクライアントを使ってチャット補完を実行します。
    # Run chat completion through the Groq client.
    """Groq API呼び出し (via OpenAI client)"""
    if groq_client is None:
        raise LlmConfigurationError("GROQ_API_KEY が未設定です。")

    sanitized_messages = _sanitize_conversation_messages(conversation_messages)
    try:
        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": sanitized_messages,
            **_chat_completion_token_limit_kwargs(model_name),
            **_groq_reasoning_kwargs(model_name),
            **_chat_completion_tool_kwargs(tools),
        }
        response = groq_client.chat.completions.create(
            **request_kwargs,
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            return json.dumps([
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in tool_calls
            ])
        return message.content
    except Exception as exc:
        _raise_provider_error(
            exc,
            provider_name="Groq",
            fallback_message="Groq API call failed.",
        )


# OpenAI互換API用のストリーム応答ジェネレータを構築して返す
# Build and return an incremental generator for OpenAI-compatible streaming responses.
# OpenAI互換のAPIクライアントからストリーム形式で応答を逐次読み込み、ジェネレータとして返します。
# Retrieve a streaming response from an OpenAI-compatible API client and yield content deltas.
def _get_openai_compatible_response_stream(
    *,
    client: OpenAI | None,
    conversation_messages: ConversationMessages,
    model_name: str,
    missing_key_message: str,
    provider_error_message: str,
    tools: list[dict[str, Any]] | None = None,
    reasoning_kwargs: dict[str, Any] | None = None,
    generation_phase: str = "default",
) -> Iterator[str]:
    # OpenAI互換APIのストリーム断片を順次返し、最後に確実に close します。
    # Yield OpenAI-compatible stream deltas and always close the stream.
    if client is None:
        raise LlmConfigurationError(missing_key_message)

    sanitized_messages = _sanitize_conversation_messages(conversation_messages)
    stream = None
    tool_call_parts: dict[int, dict[str, Any]] = {}
    output_limit_reason: str | None = None
    try:
        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": sanitized_messages,
            **_chat_completion_token_limit_kwargs(
                model_name,
                generation_phase=generation_phase,
            ),
            **_openai_reasoning_kwargs(model_name),
            **(reasoning_kwargs or {}),
            "stream": True,
            **_chat_completion_tool_kwargs(tools),
        }
        stream = client.chat.completions.create(
            **request_kwargs,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if getattr(choice, "finish_reason", None) == "length":
                # 出力がトークン上限で打ち切られたことを記録する（生成UIのJSONが壊れる主因）。
                # Record that output was cut off at the token cap (a main cause of broken
                # generative UI JSON).
                logger.warning(
                    "LLM stream truncated by token limit (model=%s, phase=%s, max_tokens=%s).",
                    model_name,
                    generation_phase,
                    max_output_tokens_for_phase(generation_phase),
                )
                output_limit_reason = "length"
            delta = choice.delta
            if getattr(delta, "content", None):
                yield delta.content

            tool_calls = getattr(delta, "tool_calls", None)
            if tool_calls:
                # OpenAI互換ストリーミングでは tool_call の name/arguments が複数 chunk に分割されます。index ごとに連結し、通常テキスト chunk と同じ iterator で最後に JSON として返します。
                # In OpenAI-compatible streaming, the name/arguments of tool_calls are split across multiple chunks. Concat them by index and return as JSON via the same iterator at the end.
                for tc in tool_calls:
                    index = int(getattr(tc, "index", 0) or 0)
                    part = tool_call_parts.setdefault(
                        index,
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    tool_call_id = getattr(tc, "id", None)
                    if tool_call_id:
                        part["id"] = tool_call_id
                    tool_call_type = getattr(tc, "type", None)
                    if tool_call_type:
                        part["type"] = tool_call_type
                    function = getattr(tc, "function", None)
                    if function is None:
                        continue
                    function_name = getattr(function, "name", None)
                    if function_name:
                        part["function"]["name"] += function_name
                    arguments = getattr(function, "arguments", None)
                    if arguments:
                        part["function"]["arguments"] += arguments

        # 打ち切られたステップでも、すでに要求されたツール呼び出しは先に流す。
        # 例外を先に投げると、収集済みのツール呼び出しごと捨ててしまう。
        # Emit the tool calls the model already requested before raising: raising first would
        # discard the tool calls collected during the truncated step.
        if tool_call_parts:
            yield json.dumps(
                [
                    tool_call_parts[index]
                    for index in sorted(tool_call_parts)
                    if tool_call_parts[index]["function"]["name"]
                ],
                ensure_ascii=False,
            )
        if output_limit_reason is not None:
            raise LlmOutputLimitError(
                f"LLM output reached the configured token limit for {model_name}.",
                reason=output_limit_reason,
            )
    except LlmServiceError:
        raise
    except Exception as exc:
        provider_name = "provider"
        if "Groq" in provider_error_message:
            provider_name = "Groq"
        _raise_provider_error(
            exc,
            provider_name=provider_name,
            fallback_message=provider_error_message,
        )
    finally:
        if stream is not None:
            stream.close()


# Groq APIを呼び出して、ストリーム形式でテキスト応答を逐次受け取る
# Call the Groq API and yield response chunks incrementally as a stream.
# Groq APIからストリーム形式で応答を逐次取得します。
# Call the Groq streaming API to yield response chunks incrementally.
def get_groq_response_stream(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    generation_phase: str = "default",
) -> Iterator[str]:
    # Groq のストリーム応答を逐次テキスト片として返します。
    # Yield Groq response chunks incrementally.
    return _get_openai_compatible_response_stream(
        client=groq_client,
        conversation_messages=conversation_messages,
        model_name=model_name,
        missing_key_message="GROQ_API_KEY が未設定です。",
        provider_error_message="Groq streaming API call failed.",
        tools=tools,
        reasoning_kwargs=_groq_reasoning_kwargs(
            model_name,
            generation_phase=generation_phase,
        ),
        generation_phase=generation_phase,
    )


# Claude Messages API向けに会話履歴を変換する
# Convert conversation history for the Claude Messages API.
# Claude Messages API はロールが交互に並ぶことを前提とする。ツール結果は user ターンへ
# 畳まれるため、その直後にテキストの user メッセージを足すと同ロールが連続してしまう。
# 同ロールが続く場合は1ターンへマージし、テキストは content ブロックとして追加する。
# The Claude Messages API expects alternating roles. Tool results are folded into a user
# turn, so appending a text user message right after would produce two consecutive user
# turns. Merge same-role neighbours into one turn, adding text as a content block.
def _append_claude_text_message(
    claude_messages: ConversationMessages,
    role: str,
    text_content: str,
) -> None:
    if not claude_messages or claude_messages[-1].get("role") != role:
        claude_messages.append({"role": role, "content": text_content})
        return

    previous_content = claude_messages[-1].get("content")
    if isinstance(previous_content, list):
        if text_content:
            previous_content.append({"type": "text", "text": text_content})
        return

    previous_text = "" if previous_content is None else str(previous_content)
    merged = "\n\n".join(part for part in (previous_text, text_content) if part)
    claude_messages[-1]["content"] = merged


def _prepare_claude_messages(
    conversation_messages: ConversationMessages,
) -> tuple[str | None, ConversationMessages]:
    system_messages: list[str] = []
    claude_messages: ConversationMessages = []

    for message in _sanitize_conversation_messages(conversation_messages):
        role = str(message.get("role", "user"))
        content = message.get("content")
        text_content = "" if content is None else str(content)

        if role in {"system", "developer"}:
            if text_content:
                system_messages.append(text_content)
            continue

        if role == "tool":
            tool_result = {
                "type": "tool_result",
                "tool_use_id": str(message.get("tool_call_id") or ""),
                "content": text_content,
            }
            if (
                claude_messages
                and claude_messages[-1]["role"] == "user"
                and isinstance(claude_messages[-1].get("content"), list)
                and all(
                    isinstance(block, dict) and block.get("type") == "tool_result"
                    for block in claude_messages[-1]["content"]
                )
            ):
                claude_messages[-1]["content"].append(tool_result)
            else:
                claude_messages.append({"role": "user", "content": [tool_result]})
            continue

        if role == "assistant" and message.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if text_content:
                blocks.append({"type": "text", "text": text_content})
            for tool_call in message["tool_calls"]:
                function = tool_call.get("function") or {}
                raw_arguments = function.get("arguments") or "{}"
                try:
                    tool_input = json.loads(raw_arguments)
                except (TypeError, json.JSONDecodeError):
                    tool_input = {}
                if not isinstance(tool_input, dict):
                    tool_input = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(tool_call.get("id") or ""),
                        "name": str(function.get("name") or ""),
                        "input": tool_input,
                    }
                )
            if (
                claude_messages
                and claude_messages[-1].get("role") == "assistant"
                and isinstance(claude_messages[-1].get("content"), list)
            ):
                claude_messages[-1]["content"].extend(blocks)
            else:
                claude_messages.append({"role": "assistant", "content": blocks})
            continue

        _append_claude_text_message(
            claude_messages,
            "assistant" if role == "assistant" else "user",
            text_content,
        )

    return ("\n\n".join(system_messages) or None), claude_messages


# OpenAI形式の関数ツール定義をClaude形式へ変換する
# Convert OpenAI function-tool definitions to Claude tool definitions.
def _prepare_claude_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    claude_tools: list[dict[str, Any]] = []
    for tool in tools or []:
        function = tool.get("function") or {}
        name = str(function.get("name") or "")
        if not name:
            continue
        input_schema = function.get("parameters")
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}
        claude_tools.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "input_schema": input_schema,
            }
        )
    return claude_tools


def _claude_tool_calls(content_blocks: Any) -> str | None:
    tool_calls: list[dict[str, Any]] = []
    for block in content_blocks or []:
        if getattr(block, "type", None) != "tool_use":
            continue
        tool_calls.append(
            {
                "id": str(getattr(block, "id", "")),
                "type": "function",
                "function": {
                    "name": str(getattr(block, "name", "")),
                    "arguments": json.dumps(getattr(block, "input", {}) or {}),
                },
            }
        )
    return json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None


def _claude_response_text(content_blocks: Any) -> str:
    return "".join(
        str(getattr(block, "text", ""))
        for block in content_blocks or []
        if getattr(block, "type", None) == "text"
    )


# Claude Messages APIを呼び出してテキスト応答または関数呼び出しデータを取得する
# Call the Claude Messages API to retrieve text responses or function-call details.
def get_claude_response(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    if claude_client is None:
        raise LlmConfigurationError("ANTHROPIC_API_KEY が未設定です。")

    system_prompt, claude_messages = _prepare_claude_messages(conversation_messages)
    try:
        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": claude_messages,
            "max_tokens": LLM_MAX_TOKENS,
        }
        if system_prompt is not None:
            request_kwargs["system"] = system_prompt
        claude_tools = _prepare_claude_tools(tools)
        if claude_tools:
            request_kwargs["tools"] = claude_tools
        response = claude_client.messages.create(**request_kwargs)
        return _claude_tool_calls(response.content) or _claude_response_text(response.content)
    except Exception as exc:
        _raise_provider_error(
            exc,
            provider_name="Anthropic Claude",
            fallback_message="Anthropic Claude API call failed.",
        )


# Claude Messages APIを呼び出してストリーム形式でテキスト応答を逐次受け取る
# Call the Claude Messages API and yield text response chunks incrementally.
def get_claude_response_stream(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    generation_phase: str = "default",
) -> Iterator[str]:
    if claude_client is None:
        raise LlmConfigurationError("ANTHROPIC_API_KEY が未設定です。")

    system_prompt, claude_messages = _prepare_claude_messages(conversation_messages)
    stream = None
    tool_call_parts: dict[int, dict[str, Any]] = {}
    output_limit_reason: str | None = None
    input_limit_reason: str | None = None
    try:
        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": claude_messages,
            "max_tokens": max_output_tokens_for_phase(generation_phase),
            "stream": True,
        }
        if system_prompt is not None:
            request_kwargs["system"] = system_prompt
        claude_tools = _prepare_claude_tools(tools)
        if claude_tools:
            request_kwargs["tools"] = claude_tools
        stream = claude_client.messages.create(**request_kwargs)
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "content_block_start":
                block = getattr(event, "content_block", None)
                if getattr(block, "type", None) == "tool_use":
                    tool_call_parts[int(getattr(event, "index", 0))] = {
                        "id": str(getattr(block, "id", "")),
                        "type": "function",
                        "function": {
                            "name": str(getattr(block, "name", "")),
                            "arguments": "",
                        },
                    }
            elif event_type == "content_block_delta":
                delta = getattr(event, "delta", None)
                delta_type = getattr(delta, "type", "")
                if delta_type == "text_delta" and getattr(delta, "text", None):
                    yield delta.text
                elif delta_type == "input_json_delta":
                    part = tool_call_parts.get(int(getattr(event, "index", 0)))
                    if part is not None:
                        part["function"]["arguments"] += str(
                            getattr(delta, "partial_json", "")
                        )
            elif event_type == "message_delta":
                delta = getattr(event, "delta", None)
                stop_reason = getattr(delta, "stop_reason", None)
                if stop_reason == "max_tokens":
                    logger.warning(
                        "Claude stream truncated by token limit "
                        "(model=%s, phase=%s, max_tokens=%s).",
                        model_name,
                        generation_phase,
                        max_output_tokens_for_phase(generation_phase),
                    )
                    output_limit_reason = str(stop_reason)
                elif stop_reason == "model_context_window_exceeded":
                    # 入力側の超過。続きを生成すると入力がさらに伸びて必ず再失敗するため、
                    # 出力上限とは別の例外にして、入力の圧縮で回復させる。
                    # This is an input overflow. Continuing would only grow the request and
                    # fail again, so raise a distinct error and recover by shrinking input.
                    logger.warning(
                        "Claude stream stopped because the input exceeded the context window "
                        "(model=%s, phase=%s).",
                        model_name,
                        generation_phase,
                    )
                    input_limit_reason = str(stop_reason)
        # 打ち切られたステップでも、すでに要求されたツール呼び出しは先に流す。
        # Emit the tool calls the model already requested before raising.
        if tool_call_parts:
            yield json.dumps(
                [tool_call_parts[index] for index in sorted(tool_call_parts)],
                ensure_ascii=False,
            )
        if input_limit_reason is not None:
            raise LlmInputLimitError(
                f"Claude rejected the request for {model_name}: input exceeds the context window.",
                reason=input_limit_reason,
            )
        if output_limit_reason is not None:
            raise LlmOutputLimitError(
                f"Claude output reached its configured limit for {model_name}.",
                reason=output_limit_reason,
            )
    except LlmServiceError:
        raise
    except Exception as exc:
        _raise_provider_error(
            exc,
            provider_name="Anthropic Claude",
            fallback_message="Anthropic Claude streaming API call failed.",
        )
    finally:
        if stream is not None and hasattr(stream, "close"):
            stream.close()


# OpenAI Responses APIを呼び出してテキスト応答を取得する
# Call the OpenAI Responses API to retrieve text responses.
# OpenAI APIを呼び出して応答を取得します（ツール呼び出しの有無に応じてChat CompletionsまたはResponses APIを使用）。
# Call the OpenAI API to retrieve the response, using Chat Completions or Responses API depending on tools.
def get_openai_response(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    # OpenAI Responses APIでテキスト応答を取得します。
    # Fetch text output via OpenAI Responses API.
    if openai_client is None:
        raise LlmConfigurationError("OPENAI_API_KEY が未設定です。")

    sanitized_messages = _prepare_openai_responses_input(
        _sanitize_conversation_messages(conversation_messages)
    )
    try:
        if tools or _conversation_has_tool_history(sanitized_messages):
            # Responses API は既存の tool/result 会話履歴と形が合わないため、tool を使うターンだけ Chat Completions 側に寄せます。
            # Since Responses API does not fit existing tool/result conversation formats, route only the tool usage turns to the Chat Completions API.
            request_kwargs: dict[str, Any] = {
                "model": model_name,
                "messages": sanitized_messages,
                **_chat_completion_token_limit_kwargs(model_name),
                **_openai_reasoning_kwargs(model_name),
                **_chat_completion_tool_kwargs(tools),
            }
            response = openai_client.chat.completions.create(
                **request_kwargs,
            )
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                return json.dumps([
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in tool_calls
                ])
            return message.content or ""
        
        response = openai_client.responses.create(
            model=model_name,
            input=sanitized_messages,
            max_output_tokens=LLM_MAX_TOKENS,
            **_openai_responses_reasoning_kwargs(model_name),
        )
        return response.output_text
    except Exception as exc:
        _raise_provider_error(
            exc,
            provider_name="OpenAI",
            fallback_message="OpenAI Responses API call failed.",
        )


# OpenAI Responses APIを呼び出して、ストリーム形式でテキスト応答を逐次受け取る
# Call the OpenAI Responses API and yield response chunks incrementally as a stream.
# OpenAI APIからストリーム形式で応答を逐次取得します。
# Call the OpenAI streaming API to yield response chunks incrementally.
def get_openai_response_stream(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    generation_phase: str = "default",
) -> Iterator[str]:
    # OpenAI Responses APIのストリーム断片を逐次返します。
    # Yield OpenAI Responses API text deltas incrementally.
    if openai_client is None:
        raise LlmConfigurationError("OPENAI_API_KEY が未設定です。")

    sanitized_messages = _prepare_openai_responses_input(
        _sanitize_conversation_messages(conversation_messages)
    )
    try:
        if tools or _conversation_has_tool_history(sanitized_messages):
            # Tool 呼び出しを含む履歴は Chat Completions の message shape に合わせてストリーミングします。
            # Stream message history containing tool calls in accordance with the Chat Completions message shape.
            yield from _get_openai_compatible_response_stream(
                client=openai_client,
                conversation_messages=sanitized_messages,
                model_name=model_name,
                missing_key_message="OPENAI_API_KEY が未設定です。",
                provider_error_message="OpenAI streaming API call failed.",
                tools=tools,
                generation_phase=generation_phase,
            )
            return

        output_limit_reason: str | None = None
        with openai_client.responses.stream(
            model=model_name,
            input=sanitized_messages,
            max_output_tokens=max_output_tokens_for_phase(generation_phase),
            **_openai_responses_reasoning_kwargs(model_name),
        ) as stream:
            for event in stream:
                if event.type == "response.output_text.delta":
                    delta = event.delta
                    if delta:
                        yield delta
                elif event.type == "response.incomplete":
                    # 出力がトークン上限で打ち切られたことを記録する（生成UIのJSONが壊れる主因）。
                    # Record that output was cut off at the token cap (a main cause of
                    # broken generative UI JSON).
                    logger.warning(
                        "OpenAI Responses stream incomplete "
                        "(model=%s, phase=%s, max_output_tokens=%s).",
                        model_name,
                        generation_phase,
                        max_output_tokens_for_phase(generation_phase),
                    )
                    response = getattr(event, "response", None)
                    incomplete_details = getattr(response, "incomplete_details", None)
                    output_limit_reason = str(
                        getattr(incomplete_details, "reason", None) or "incomplete"
                    )
        if output_limit_reason in {"max_output_tokens", "max_tokens"}:
            raise LlmOutputLimitError(
                f"OpenAI output reached the configured token limit for {model_name}.",
                reason=output_limit_reason,
            )
        if output_limit_reason is not None:
            raise LlmProviderError(
                f"OpenAI returned an incomplete response ({output_limit_reason})."
            )
    except LlmServiceError:
        raise
    except Exception as exc:
        _raise_provider_error(
            exc,
            provider_name="OpenAI",
            fallback_message="OpenAI Responses streaming API call failed.",
        )


# 与えられたモデル名がClaudeファミリーのものか確認する
# Check if the given model name belongs to the Claude family.
def is_claude_model(model_name: str) -> bool:
    return model_name in VALID_CLAUDE_MODELS


# 与えられたモデル名がGroqファミリーのものか確認する
# Check if the given model name belongs to the Groq family.
# 指定されたモデル名がGroqファミリーに属するか判定します。
# Check whether the specified model name belongs to the Groq family.
def is_groq_model(model_name: str) -> bool:
    # モデル名が Groq 系かを判定します。
    # Check whether the selected model belongs to Groq.
    return model_name in VALID_GROQ_MODELS


# 与えられたモデル名がOpenAIファミリーのものか確認する
# Check if the given model name belongs to the OpenAI family.
# 指定されたモデル名がOpenAIファミリーに属するか判定します。
# Check whether the specified model name belongs to the OpenAI family.
def is_openai_model(model_name: str) -> bool:
    # モデル名が OpenAI 系かを判定します。
    # Check whether the selected model belongs to OpenAI.
    return model_name in VALID_OPENAI_MODELS


# 指定されたモデルがストリーミング（逐次出力）に対応しているか確認する
# Verify if the specified model supports streaming/SSE output in this application.
# 指定されたモデル名がストリーミング応答をサポートしているか判定します。
# Check whether the specified model name supports streaming/SSE output.
def is_streaming_model(model_name: str) -> bool:
    # 現在SSE配信に対応しているモデルかを判定します。
    # Check whether the selected model supports SSE streaming in this app.
    return is_claude_model(model_name) or is_groq_model(model_name) or is_openai_model(model_name)


# 指定されたモデル名がサポート対象であるか確認し、無効であればエラーを投げる
# Validate whether the specified model name is supported, raising an error if invalid.
# 指定されたモデル名が有効（いずれかのファミリーに属する）か検証します。無効な場合は例外を送出します。
# Validate if the model name is supported, raising a LlmInvalidModelError if not.
def validate_model_name(model_name: str) -> None:
    if is_claude_model(model_name) or is_groq_model(model_name) or is_openai_model(model_name):
        return
    _raise_invalid_model_error(model_name)


# 指定モデルでプロバイダ（Claude、Groq、OpenAI等）を自動で振り分けてチャット完了応答を取得する
# Route to the appropriate LLM provider based on the model name and return the chat completion response.
# モデル名に応じてプロバイダを自動判定し、チャット完了応答を取得します。
# Automatically route the request based on the model name and return the LLM response.
def get_llm_response(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> str | None:
    # 指定モデル名でプロバイダを振り分け、不正モデルは例外として扱います。
    # Route provider by model name and raise on invalid models.
    validate_model_name(model_name)
    if is_claude_model(model_name):
        return get_claude_response(conversation_messages, model_name, tools=tools)
    if is_groq_model(model_name):
        return get_groq_response(conversation_messages, model_name, tools=tools)
    if is_openai_model(model_name):
        return get_openai_response(conversation_messages, model_name, tools=tools)
    raise RuntimeError("Unreachable model dispatch branch in get_llm_response.")


# チャット完了APIを使ってJSON形式のオブジェクト出力を強制し、応答を取得する
# Request and retrieve a chat completion response formatted strictly as a JSON object.
# JSONオブジェクト形式での出力を指定して、Chat Completions APIから応答を取得します。
# Fetch a JSON-formatted response from the Chat Completions API.
def _get_chat_completions_json_response(
    *,
    client: OpenAI | None,
    conversation_messages: ConversationMessages,
    model_name: str,
    provider_name: str,
    missing_key_message: str,
    fallback_message: str,
) -> str | None:
    if client is None:
        raise LlmConfigurationError(missing_key_message)

    sanitized_messages = _sanitize_conversation_messages(conversation_messages)
    try:
        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": sanitized_messages,
            **_chat_completion_token_limit_kwargs(model_name),
            **(_groq_reasoning_kwargs(model_name) if provider_name == "Groq" else {}),
            **_openai_reasoning_kwargs(model_name),
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        response = client.chat.completions.create(
            **request_kwargs,
        )
        return response.choices[0].message.content
    except Exception as exc:
        _raise_provider_error(
            exc,
            provider_name=provider_name,
            fallback_message=fallback_message,
        )


# OpenAI Responses APIを利用してJSON形式のオブジェクト応答を取得する
# Call the OpenAI Responses API to retrieve a response structured as a JSON object.
# JSONオブジェクト形式での出力を指定して、OpenAI Responses APIから応答を取得します。
# Fetch a JSON-formatted response from the OpenAI Responses API.
def _get_openai_responses_json_response(
    conversation_messages: ConversationMessages,
    model_name: str,
) -> str | None:
    if openai_client is None:
        raise LlmConfigurationError("OPENAI_API_KEY が未設定です。")

    sanitized_messages = _prepare_openai_responses_input(
        _sanitize_conversation_messages(conversation_messages)
    )
    try:
        response = openai_client.responses.create(
            model=model_name,
            input=sanitized_messages,
            max_output_tokens=LLM_MAX_TOKENS,
            **_openai_responses_reasoning_kwargs(model_name),
            text={"format": {"type": "json_object"}},
        )
        return response.output_text
    except Exception as exc:
        _raise_provider_error(
            exc,
            provider_name="OpenAI",
            fallback_message="OpenAI Responses JSON API call failed.",
        )


# 指定されたモデルを使用してJSON形式のLLM応答を取得する
# Fetch a JSON object response from the LLM based on the selected model name.
# 指定されたモデルでJSONオブジェクト形式の応答を取得します。
# Retrieve a JSON object response from the LLM based on the selected model name.
def get_llm_json_response(
    conversation_messages: ConversationMessages, model_name: str
) -> str | None:
    # JSONオブジェクト形式の出力を強制してLLMから応答を取得します。失敗時は LlmServiceError を送出します。
    # Request and retrieve a chat completion response formatted strictly as a JSON object, raising LlmServiceError on failure.
    validate_model_name(model_name)
    if is_claude_model(model_name):
        return get_claude_response(conversation_messages, model_name)
    if is_groq_model(model_name):
        return _get_chat_completions_json_response(
            client=groq_client,
            conversation_messages=conversation_messages,
            model_name=model_name,
            provider_name="Groq",
            missing_key_message="GROQ_API_KEY が未設定です。",
            fallback_message="Groq JSON API call failed.",
        )
    if is_openai_model(model_name):
        return _get_openai_responses_json_response(conversation_messages, model_name)
    raise RuntimeError("Unreachable model dispatch branch in get_llm_json_response.")


# 指定モデルでプロバイダを自動で振り分けてチャット完了応答をストリーミング配信形式で取得する
# Route to the appropriate provider based on the model and yield streaming output deltas.
# モデル名に応じてプロバイダを自動判定し、ストリーム形式でテキスト応答を逐次取得します。
# Automatically route the request based on the model name and yield response chunks as a stream.
def get_llm_response_stream(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    generation_phase: str = "default",
) -> Iterator[str]:
    # 指定モデル名でストリーム可能なプロバイダを振り分けます。
    # Route streaming providers by model name and raise on invalid models.
    validate_model_name(model_name)
    if is_claude_model(model_name):
        return get_claude_response_stream(
            conversation_messages,
            model_name,
            tools=tools,
            generation_phase=generation_phase,
        )
    if is_groq_model(model_name):
        if generation_phase == "default":
            return get_groq_response_stream(conversation_messages, model_name, tools=tools)
        return get_groq_response_stream(
            conversation_messages, model_name, tools=tools, generation_phase=generation_phase
        )
    if is_openai_model(model_name):
        if generation_phase == "default":
            return get_openai_response_stream(conversation_messages, model_name, tools=tools)
        return get_openai_response_stream(
            conversation_messages, model_name, tools=tools, generation_phase=generation_phase
        )
    raise RuntimeError("Unreachable model dispatch branch in get_llm_response_stream.")
