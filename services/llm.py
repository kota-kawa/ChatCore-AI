"""LLM service module using OpenAI client for multiple providers."""

import json
import logging
import os
import re
from collections.abc import Iterator
from typing import Any

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
    # 日本語: OpenAI SDKの例外クラスが存在しない（インポートできない）場合のダミー例外クラスです。
    # English: Dummy exception class used when OpenAI SDK exception classes are not available for import.
    class _UnavailableOpenAIError(Exception):
        pass

    APIConnectionError = _UnavailableOpenAIError  # type: ignore[assignment]
    APIStatusError = _UnavailableOpenAIError  # type: ignore[assignment]
    APITimeoutError = _UnavailableOpenAIError  # type: ignore[assignment]
    AuthenticationError = _UnavailableOpenAIError  # type: ignore[assignment]
    RateLimitError = _UnavailableOpenAIError  # type: ignore[assignment]


# 日本語: 環境変数から正の整数値を取得します。無効な場合はデフォルト値を返します。
# English: Retrieve a positive integer from environment variables, returning the default if invalid.
def _get_positive_int_env(name: str, default: int) -> int:
    # 正の整数のみ採用し、無効値は安全側で既定値へ戻す
    # Accept only positive integers and fallback to default on invalid values.
    raw = os.environ.get(name)
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if raw is None:
        return default
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# 日本語: 環境変数から0以上の整数値を取得します。無効な場合はデフォルト値を返します。
# English: Retrieve a non-negative integer from environment variables, returning the default if invalid.
def _get_non_negative_int_env(name: str, default: int) -> int:
    # 0以上の整数を採用し、無効値は既定値へ戻す（再試行回数などで0を許容する）
    # Accept zero or positive integers (e.g. retry counts) and fallback on invalid values.
    raw = os.environ.get(name)
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if raw is None:
        return default
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


# 日本語: 大文字・小文字を問わず、環境変数からGeminiのAPIキーを取得します。
# English: Retrieve the Gemini API key from environment variables (case-insensitive).
def _get_gemini_api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "") or os.environ.get("Gemini_API_KEY", "")


GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GPT_OSS_120B_MODEL = "openai/gpt-oss-120b"
GPT_OSS_20B_LEGACY_MODEL = "openai/gpt-oss-20b"
GPT_5_MINI_MODEL = "gpt-5-mini"
GPT_5_MINI_2025_08_07_MODEL = "gpt-5-mini-2025-08-07"
OPENAI_DEFAULT_MODEL = (
    os.environ.get("OPENAI_DEFAULT_MODEL", GPT_5_MINI_MODEL).strip()
    or GPT_5_MINI_MODEL
)
GEMINI_DEFAULT_MODEL = os.environ.get("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash")
LLM_MAX_TOKENS = _get_positive_int_env("LLM_MAX_TOKENS", 4096)
LLM_REQUEST_TIMEOUT_SECONDS = 30.0
# 一時的な接続失敗を吸収するため既定の再試行回数を増やす（環境変数で調整可能）
# Retry transient connection failures by default; configurable via env var.
LLM_MAX_RETRIES = _get_non_negative_int_env("LLM_MAX_RETRIES", 2)

REDACTED_SENSITIVE_VALUE = "[REDACTED-SENSITIVE]"
OPENAI_MARKDOWN_REENABLE_PREFIX = "Formatting re-enabled"
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
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
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# サポート対象モデルを明示し、入力バリデーションの単一情報源にする
# Keep supported model names explicit as the single validation source.
# Valid model names
VALID_GEMINI_MODELS = {
    "gemini-2.5-flash",
}
VALID_GROQ_MODELS = {GROQ_MODEL, GPT_OSS_120B_MODEL, GPT_OSS_20B_LEGACY_MODEL}
VALID_OPENAI_MODELS = {
    OPENAI_DEFAULT_MODEL,
    GPT_5_MINI_MODEL,
    GPT_5_MINI_2025_08_07_MODEL,
}

groq_api_key = os.environ.get("GROQ_API_KEY", "")
gemini_api_key = _get_gemini_api_key()
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
gemini_client = (
    OpenAI(
        api_key=gemini_api_key,
        base_url=GEMINI_BASE_URL,
        timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )
    if gemini_api_key
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


# 日本語: LLMサービス全体に関する基本例外クラス。
# English: Base exception class for LLM service-related errors.
class LlmServiceError(RuntimeError):
    # LLM連携で発生する例外の基底クラス
    # Base exception class for LLM integration failures.
    pass


# 日本語: LLMサービスの設定不備に関する例外クラス。
# English: Exception class for LLM service configuration errors.
class LlmConfigurationError(LlmServiceError):
    # APIキー未設定など、設定不備に関する例外
    # Configuration-related exception (e.g., missing API key).
    pass


# 日本語: LLMプロバイダ呼び出しエラーに関する例外クラス。
# English: Exception class for LLM provider invocation errors.
class LlmProviderError(LlmServiceError):
    # 外部プロバイダ呼び出し失敗に関する例外
    # Provider-call failure exception.
    retryable = False

    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


# 日本語: 再試行可能なLLMプロバイダエラーに関する例外クラス。
# English: Exception class for retryable LLM provider errors.
class LlmRetryableProviderError(LlmProviderError):
    # 再試行により回復可能な可能性が高いプロバイダ例外
    # Provider-call failure that is likely retryable.
    retryable = True


# 日本語: レート制限によるLLMプロバイダエラーに関する例外クラス。
# English: Exception class for LLM provider rate limit errors.
class LlmRateLimitError(LlmRetryableProviderError):
    # レート制限による失敗
    # Provider rate-limit failure.
    pass


# 日本語: タイムアウトによるLLMプロバイダエラーに関する例外クラス。
# English: Exception class for LLM provider timeout errors.
class LlmTimeoutError(LlmRetryableProviderError):
    # タイムアウトによる失敗
    # Provider timeout failure.
    pass


# 日本語: ネットワークエラーによるLLMプロバイダエラーに関する例外クラス。
# English: Exception class for LLM provider network errors.
class LlmNetworkError(LlmRetryableProviderError):
    # ネットワーク到達性による失敗
    # Provider network/connectivity failure.
    pass


# 日本語: 上流サービスのエラーによるLLMプロバイダエラーに関する例外クラス。
# English: Exception class for LLM provider upstream service errors.
class LlmUpstreamServiceError(LlmRetryableProviderError):
    # 上流サービス障害 (5xx)
    # Upstream provider service failure (5xx).
    pass


# 日本語: 認証エラーによるLLMプロバイダエラーに関する例外クラス。
# English: Exception class for LLM provider authentication errors.
class LlmAuthenticationError(LlmProviderError):
    # 認証・権限不備による失敗
    # Provider authentication/authorization failure.
    pass


# 日本語: 指定されたモデルが無効である場合の例外クラス。
# English: Exception class for invalid LLM model specifications.
class LlmInvalidModelError(LlmServiceError):
    # 未サポートモデル指定時の例外
    # Unsupported model selection exception.
    pass


# 与えられた例外がLLMプロバイダの一時的なエラー（再試行可能）かどうかを判定する
# Determine whether the given exception is a transient/retryable LLM provider error.
# 日本語: 与えられた例外が再試行可能なLLMプロバイダエラーかどうかを判定します。
# English: Check whether the given exception is a retryable LLM provider error.
def is_retryable_llm_error(exc: BaseException) -> bool:
    return isinstance(exc, LlmRetryableProviderError)


# HTTPレスポンスヘッダからRetry-After秒数を抽出する
# Extract the Retry-After value (in seconds) from the HTTP response headers.
# 日本語: HTTPレスポンスヘッダーからRetry-Afterの値を抽出し、秒数に変換します。
# English: Extract the Retry-After value from HTTP response headers and convert it to seconds.
def _extract_retry_after_seconds(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if headers is None or not hasattr(headers, "get"):
        return None
    raw_retry_after = headers.get("retry-after")
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if raw_retry_after is None:
        return None
    try:
        retry_after = int(str(raw_retry_after).strip())
    except (TypeError, ValueError):
        return None
    return retry_after if retry_after >= 0 else None


# 外部OpenAI/Groq/Geminiクライアントの例外をアプリケーション独自のLlmProviderError派生例外にマッピングする
# Map raw exceptions from OpenAI/Groq/Gemini SDKs to application-specific LlmProviderError sub-classes.
# 日本語: LLMプロバイダSDK独自の例外を、アプリケーション共通のLLM例外にマッピングします。
# English: Map provider-specific exceptions to application-specific LLM exceptions.
def _map_provider_exception(
    exc: BaseException,
    *,
    provider_name: str,
    fallback_message: str,
) -> LlmProviderError:
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if isinstance(exc, LlmProviderError):
        return exc

    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if isinstance(exc, RateLimitError):
        return LlmRateLimitError(
            f"{provider_name} API rate limit exceeded.",
            retry_after_seconds=_extract_retry_after_seconds(exc),
        )
    if isinstance(exc, APITimeoutError):
        return LlmTimeoutError(f"{provider_name} API request timed out.")
    if isinstance(exc, APIConnectionError):
        return LlmNetworkError(f"{provider_name} API connection failed.")
    if isinstance(exc, AuthenticationError):
        return LlmAuthenticationError(f"{provider_name} API authentication failed.")
    if isinstance(exc, APIStatusError):
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

    return LlmProviderError(fallback_message)


# マッピングされたLLMプロバイダエラーをログ出力し、例外として発生させる
# Log and raise the mapped LLM provider error.
# 日本語: LLMプロバイダ例外を共通例外に変換してログ出力し、送出します。
# English: Map the LLM provider exception, log it, and raise it.
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
# 日本語: 無効なモデルが指定された場合のエラーログを出力し、例外を送出します。
# English: Log an error message and raise a LlmInvalidModelError for an invalid model name.
def _raise_invalid_model_error(model_name: str) -> None:
    valid_models = sorted(VALID_GEMINI_MODELS | VALID_GROQ_MODELS | VALID_OPENAI_MODELS)
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
# 日本語: モデルファミリーに合わせて、最大トークン数制限を指定する引数辞書を構築します。
# English: Construct the keyword arguments dictionary for max token limits based on the model family.
def _chat_completion_token_limit_kwargs(model_name: str) -> dict[str, int]:
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if is_openai_model(model_name):
        return {"max_completion_tokens": LLM_MAX_TOKENS}
    return {"max_tokens": LLM_MAX_TOKENS}


# ツール呼び出しの設定用キーワード引数を構築する
# Build tool-choice keyword arguments for chat completions.
# 日本語: LLMツール（関数呼び出し）指定用の引数辞書を構築します。
# English: Construct the keyword arguments dictionary for tool specification.
def _chat_completion_tool_kwargs(
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if not tools:
        return {}
    return {
        "tools": tools,
        "tool_choice": "auto",
    }


# 会話履歴にツール（関数呼び出し）の履歴が含まれているかチェックする
# Check if the conversation messages history contains tool-call results or requests.
# 日本語: 会話履歴にツール（関数呼び出し）の呼び出しや結果が含まれているか判定します。
# English: Check whether the conversation history contains tool calls or tool response messages.
def _conversation_has_tool_history(conversation_messages: ConversationMessages) -> bool:
    # 日本語: イテレータから要素を順に取得し、反復処理を行います。
    # English: Iterate over the elements sequentially and perform operations.
    for message in conversation_messages:
        role = str(message.get("role", ""))
        if role == "tool":
            return True
        if message.get("tool_calls"):
            return True
    return False


# テキスト内にあるAPIキーやパスワードなどの機密情報を伏せ字にする
# Redact sensitive information (API keys, passwords) from the given text.
# 日本語: テキスト中のAPIキーやシークレットなどの機密情報をマスクします。
# English: Redact sensitive information (API keys, secrets) found in the text.
def _redact_sensitive_text(value: str) -> str:
    # 既知トークン形式と key=value 形式の両方を伏せ字化する
    # Redact both known token patterns and key=value style secrets.
    redacted = value
    # 日本語: イテレータから要素を順に取得し、反復処理を行います。
    # English: Iterate over the elements sequentially and perform operations.
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub(REDACTED_SENSITIVE_VALUE, redacted)
    # 日本語: イテレータから要素を順に取得し、反復処理を行います。
    # English: Iterate over the elements sequentially and perform operations.
    for pattern in _SENSITIVE_ASSIGNMENT_PATTERNS:
        redacted = pattern.sub(r"\1=<REDACTED-SENSITIVE>", redacted)
    return redacted


# 会話メッセージ履歴内のすべての機密情報（APIキー等）をマスク処理する
# Redact sensitive information from all conversation messages in the history.
# 日本語: 会話履歴メッセージから機密情報を一括してマスク処理します。
# English: Sanitize and redact sensitive information from all conversation messages.
def _sanitize_conversation_messages(
    conversation_messages: ConversationMessages,
) -> ConversationMessages:
    sanitized_messages: ConversationMessages = []
    redacted_message_count = 0

    # 日本語: イテレータから要素を順に取得し、反復処理を行います。
    # English: Iterate over the elements sequentially and perform operations.
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

    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if redacted_message_count > 0:
        logger.warning(
            "Redacted sensitive content in %s message(s) before LLM request.",
            redacted_message_count,
        )
    return sanitized_messages


# OpenAI Responses API形式の入力メッセージに変換し、システムロール等を適切に修正する
# Prepare conversation messages for OpenAI Responses API, converting system roles to developer.
# 日本語: OpenAI Responses APIの入力フォーマットに合わせてメッセージを加工します（systemをdeveloperに変更するなど）。
# English: Prepare messages for OpenAI Responses API format, such as renaming system to developer.
def _prepare_openai_responses_input(
    conversation_messages: ConversationMessages,
) -> ConversationMessages:
    prepared_messages: ConversationMessages = []
    markdown_reenabled = False

    # 日本語: イテレータから要素を順に取得し、反復処理を行います。
    # English: Iterate over the elements sequentially and perform operations.
    for message in conversation_messages:
        new_msg = dict(message)
        role = str(new_msg.get("role", "user"))
        raw_content = new_msg.get("content")
        
        if raw_content is None:
            normalized_content = None
        else:
            normalized_content = raw_content if isinstance(raw_content, str) else str(raw_content)

        if role == "system":
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
# 日本語: Groq APIを呼び出して応答を取得します（ツール定義がある場合は関数呼び出しデータを含むJSONを返すことがあります）。
# English: Call the Groq API to retrieve the response (may return a JSON string for tool calls if tools are provided).
def get_groq_response(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> str | None:
    # Groq 向けクライアントを使ってチャット補完を実行する
    # Run chat completion through the Groq client.
    """Groq API呼び出し (via OpenAI client)"""
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if groq_client is None:
        raise LlmConfigurationError("GROQ_API_KEY が未設定です。")

    sanitized_messages = _sanitize_conversation_messages(conversation_messages)
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": sanitized_messages,
            **_chat_completion_token_limit_kwargs(model_name),
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
# 日本語: OpenAI互換のAPIクライアントからストリーム形式で応答を逐次読み込み、ジェネレータとして返します。
# English: Retrieve a streaming response from an OpenAI-compatible API client and yield content deltas.
def _get_openai_compatible_response_stream(
    *,
    client: OpenAI | None,
    conversation_messages: ConversationMessages,
    model_name: str,
    missing_key_message: str,
    provider_error_message: str,
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[str]:
    # OpenAI互換APIのストリーム断片を順次返し、最後に確実に close する
    # Yield OpenAI-compatible stream deltas and always close the stream.
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if client is None:
        raise LlmConfigurationError(missing_key_message)

    sanitized_messages = _sanitize_conversation_messages(conversation_messages)
    stream = None
    tool_call_parts: dict[int, dict[str, Any]] = {}
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": sanitized_messages,
            **_chat_completion_token_limit_kwargs(model_name),
            "stream": True,
            **_chat_completion_tool_kwargs(tools),
        }
        stream = client.chat.completions.create(
            **request_kwargs,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                yield delta.content

            tool_calls = getattr(delta, "tool_calls", None)
            if tool_calls:
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

        if tool_call_parts:
            yield json.dumps(
                [
                    tool_call_parts[index]
                    for index in sorted(tool_call_parts)
                    if tool_call_parts[index]["function"]["name"]
                ],
                ensure_ascii=False,
            )
    except Exception as exc:
        provider_name = "provider"
        if "Groq" in provider_error_message:
            provider_name = "Groq"
        elif "Gemini" in provider_error_message:
            provider_name = "Google Gemini"
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
# 日本語: Groq APIからストリーム形式で応答を逐次取得します。
# English: Call the Groq streaming API to yield response chunks incrementally.
def get_groq_response_stream(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[str]:
    # Groq のストリーム応答を逐次テキスト片として返す
    # Yield Groq response chunks incrementally.
    return _get_openai_compatible_response_stream(
        client=groq_client,
        conversation_messages=conversation_messages,
        model_name=model_name,
        missing_key_message="GROQ_API_KEY が未設定です。",
        provider_error_message="Groq streaming API call failed.",
        tools=tools,
    )


# Google Gemini APIを呼び出してモデルからのテキスト応答または関数呼び出しデータを取得する
# Call the Google Gemini API to retrieve text responses or function-call details.
# 日本語: Gemini API（OpenAI互換エンドポイント）を呼び出して応答を取得します。
# English: Call the Gemini API (via OpenAI-compatible endpoint) to retrieve the response.
def get_gemini_response(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> str | None:
    # Gemini 向けクライアントを使ってチャット補完を実行する
    # Run chat completion through the Gemini client.
    """Google Gemini API呼び出し (via OpenAI client)"""
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if gemini_client is None:
        raise LlmConfigurationError("GEMINI_API_KEY または Gemini_API_KEY が未設定です。")

    sanitized_messages = _sanitize_conversation_messages(conversation_messages)
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": sanitized_messages,
            **_chat_completion_token_limit_kwargs(model_name),
            **_chat_completion_tool_kwargs(tools),
        }
        response = gemini_client.chat.completions.create(
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
            provider_name="Google Gemini",
            fallback_message="Google Gemini API call failed.",
        )


# Google Gemini APIを呼び出して、ストリーム形式でテキスト応答を逐次受け取る
# Call the Google Gemini API and yield response chunks incrementally as a stream.
# 日本語: Gemini APIからストリーム形式で応答を逐次取得します。
# English: Call the Gemini streaming API to yield response chunks incrementally.
def get_gemini_response_stream(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[str]:
    # Gemini のストリーム応答を逐次テキスト片として返す
    # Yield Gemini response chunks incrementally.
    return _get_openai_compatible_response_stream(
        client=gemini_client,
        conversation_messages=conversation_messages,
        model_name=model_name,
        missing_key_message="GEMINI_API_KEY または Gemini_API_KEY が未設定です。",
        provider_error_message="Google Gemini streaming API call failed.",
        tools=tools,
    )


# OpenAI Responses APIを呼び出してテキスト応答を取得する
# Call the OpenAI Responses API to retrieve text responses.
# 日本語: OpenAI APIを呼び出して応答を取得します（ツール呼び出しの有無に応じてChat CompletionsまたはResponses APIを使用）。
# English: Call the OpenAI API to retrieve the response, using Chat Completions or Responses API depending on tools.
def get_openai_response(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    # OpenAI Responses APIでテキスト応答を取得する
    # Fetch text output via OpenAI Responses API.
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if openai_client is None:
        raise LlmConfigurationError("OPENAI_API_KEY が未設定です。")

    sanitized_messages = _prepare_openai_responses_input(
        _sanitize_conversation_messages(conversation_messages)
    )
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        # Tool-call conversations use Chat Completions-compatible message shapes.
        if tools or _conversation_has_tool_history(sanitized_messages):
            request_kwargs: dict[str, Any] = {
                "model": model_name,
                "messages": sanitized_messages,
                **_chat_completion_token_limit_kwargs(model_name),
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
# 日本語: OpenAI APIからストリーム形式で応答を逐次取得します。
# English: Call the OpenAI streaming API to yield response chunks incrementally.
def get_openai_response_stream(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[str]:
    # OpenAI Responses APIのストリーム断片を逐次返す
    # Yield OpenAI Responses API text deltas incrementally.
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if openai_client is None:
        raise LlmConfigurationError("OPENAI_API_KEY が未設定です。")

    sanitized_messages = _prepare_openai_responses_input(
        _sanitize_conversation_messages(conversation_messages)
    )
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        if tools or _conversation_has_tool_history(sanitized_messages):
            # Use chat.completions for tool support and tool-result followups.
            yield from _get_openai_compatible_response_stream(
                client=openai_client,
                conversation_messages=sanitized_messages,
                model_name=model_name,
                missing_key_message="OPENAI_API_KEY が未設定です。",
                provider_error_message="OpenAI streaming API call failed.",
                tools=tools,
            )
            return

        with openai_client.responses.stream(
            model=model_name,
            input=sanitized_messages,
            max_output_tokens=LLM_MAX_TOKENS,
        ) as stream:
            for event in stream:
                if event.type == "response.output_text.delta":
                    delta = event.delta
                    if delta:
                        yield delta
    except Exception as exc:
        _raise_provider_error(
            exc,
            provider_name="OpenAI",
            fallback_message="OpenAI Responses streaming API call failed.",
        )


# 与えられたモデル名がGeminiファミリーのものか確認する
# Check if the given model name belongs to the Gemini family.
# 日本語: 指定されたモデル名がGeminiファミリーに属するか判定します。
# English: Check whether the specified model name belongs to the Gemini family.
def is_gemini_model(model_name: str) -> bool:
    # モデル名が Gemini 系かを判定する
    # Check whether the selected model belongs to Gemini.
    return model_name in VALID_GEMINI_MODELS


# 与えられたモデル名がGroqファミリーのものか確認する
# Check if the given model name belongs to the Groq family.
# 日本語: 指定されたモデル名がGroqファミリーに属するか判定します。
# English: Check whether the specified model name belongs to the Groq family.
def is_groq_model(model_name: str) -> bool:
    # モデル名が Groq 系かを判定する
    # Check whether the selected model belongs to Groq.
    return model_name in VALID_GROQ_MODELS


# 与えられたモデル名がOpenAIファミリーのものか確認する
# Check if the given model name belongs to the OpenAI family.
# 日本語: 指定されたモデル名がOpenAIファミリーに属するか判定します。
# English: Check whether the specified model name belongs to the OpenAI family.
def is_openai_model(model_name: str) -> bool:
    # モデル名が OpenAI 系かを判定する
    # Check whether the selected model belongs to OpenAI.
    return model_name in VALID_OPENAI_MODELS


# 指定されたモデルがストリーミング（逐次出力）に対応しているか確認する
# Verify if the specified model supports streaming/SSE output in this application.
# 日本語: 指定されたモデル名がストリーミング応答をサポートしているか判定します。
# English: Check whether the specified model name supports streaming/SSE output.
def is_streaming_model(model_name: str) -> bool:
    # 現在SSE配信に対応しているモデルかを判定する
    # Check whether the selected model supports SSE streaming in this app.
    return is_gemini_model(model_name) or is_groq_model(model_name) or is_openai_model(model_name)


# 指定されたモデル名がサポート対象であるか確認し、無効であればエラーを投げる
# Validate whether the specified model name is supported, raising an error if invalid.
# 日本語: 指定されたモデル名が有効（いずれかのファミリーに属する）か検証します。無効な場合は例外を送出します。
# English: Validate if the model name is supported, raising a LlmInvalidModelError if not.
def validate_model_name(model_name: str) -> None:
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if is_gemini_model(model_name) or is_groq_model(model_name) or is_openai_model(model_name):
        return
    _raise_invalid_model_error(model_name)


# 指定モデルでプロバイダ（Gemini、Groq、OpenAI等）を自動で振り分けてチャット完了応答を取得する
# Route to the appropriate LLM provider based on the model name and return the chat completion response.
# 日本語: モデル名に応じてプロバイダを自動判定し、チャット完了応答を取得します。
# English: Automatically route the request based on the model name and return the LLM response.
def get_llm_response(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> str | None:
    # 指定モデル名でプロバイダを振り分け、不正モデルは例外として扱う
    # Route provider by model name and raise on invalid models.
    validate_model_name(model_name)
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if is_gemini_model(model_name):
        return get_gemini_response(conversation_messages, model_name, tools=tools)
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if is_groq_model(model_name):
        return get_groq_response(conversation_messages, model_name, tools=tools)
    if is_openai_model(model_name):
        return get_openai_response(conversation_messages, model_name, tools=tools)
    raise RuntimeError("Unreachable model dispatch branch in get_llm_response.")


# チャット完了APIを使ってJSON形式のオブジェクト出力を強制し、応答を取得する
# Request and retrieve a chat completion response formatted strictly as a JSON object.
# 日本語: JSONオブジェクト形式での出力を指定して、Chat Completions APIから応答を取得します。
# English: Fetch a JSON-formatted response from the Chat Completions API.
def _get_chat_completions_json_response(
    *,
    client: OpenAI | None,
    conversation_messages: ConversationMessages,
    model_name: str,
    provider_name: str,
    missing_key_message: str,
    fallback_message: str,
) -> str | None:
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if client is None:
        raise LlmConfigurationError(missing_key_message)

    sanitized_messages = _sanitize_conversation_messages(conversation_messages)
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": sanitized_messages,
            **_chat_completion_token_limit_kwargs(model_name),
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
# 日本語: JSONオブジェクト形式での出力を指定して、OpenAI Responses APIから応答を取得します。
# English: Fetch a JSON-formatted response from the OpenAI Responses API.
def _get_openai_responses_json_response(
    conversation_messages: ConversationMessages,
    model_name: str,
) -> str | None:
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if openai_client is None:
        raise LlmConfigurationError("OPENAI_API_KEY が未設定です。")

    sanitized_messages = _prepare_openai_responses_input(
        _sanitize_conversation_messages(conversation_messages)
    )
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        response = openai_client.responses.create(
            model=model_name,
            input=sanitized_messages,
            max_output_tokens=LLM_MAX_TOKENS,
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
# 日本語: 指定されたモデルでJSONオブジェクト形式の応答を取得します。
# English: Retrieve a JSON object response from the LLM based on the selected model name.
def get_llm_json_response(
    conversation_messages: ConversationMessages, model_name: str
) -> str | None:
    # JSONオブジェクト形式の出力を強制してLLMから応答を取得する。
    # 失敗時はLlmServiceErrorを送出する。
    validate_model_name(model_name)
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if is_gemini_model(model_name):
        return _get_chat_completions_json_response(
            client=gemini_client,
            conversation_messages=conversation_messages,
            model_name=model_name,
            provider_name="Google Gemini",
            missing_key_message="GEMINI_API_KEY または Gemini_API_KEY が未設定です。",
            fallback_message="Google Gemini JSON API call failed.",
        )
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
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
# 日本語: モデル名に応じてプロバイダを自動判定し、ストリーム形式でテキスト応答を逐次取得します。
# English: Automatically route the request based on the model name and yield response chunks as a stream.
def get_llm_response_stream(
    conversation_messages: ConversationMessages,
    model_name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[str]:
    # 指定モデル名でストリーム可能なプロバイダを振り分ける
    # Route streaming providers by model name and raise on invalid models.
    validate_model_name(model_name)
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if is_gemini_model(model_name):
        return get_gemini_response_stream(conversation_messages, model_name, tools=tools)
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if is_groq_model(model_name):
        return get_groq_response_stream(conversation_messages, model_name, tools=tools)
    if is_openai_model(model_name):
        return get_openai_response_stream(conversation_messages, model_name, tools=tools)
    raise RuntimeError("Unreachable model dispatch branch in get_llm_response_stream.")
