from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any, Literal

from fastapi import Request


Locale = Literal["ja", "en"]
SUPPORTED_LOCALES: tuple[Locale, ...] = ("ja", "en")
DEFAULT_LOCALE: Locale = "ja"
LOCALE_COOKIE_NAME = "chatcore_locale"
PREFERRED_LOCALE_SESSION_KEY = "preferred_locale"
PREFERRED_LOCALE_LOADED_SESSION_KEY = "_preferred_locale_loaded"
_JAPANESE_REQUEST_PATTERN = re.compile(
    r"(?:して|ください|お願い|作成|提案|改善|修正|要約|翻訳|教えて|書いて|作って)"
)
_ENGLISH_REQUEST_PATTERN = re.compile(
    r"\b(?:please|create|write|make|summarize|translate|improve|revise|help|"
    r"can you|could you)\b",
    re.IGNORECASE,
)

_current_locale: ContextVar[Locale] = ContextVar(
    "chatcore_current_locale",
    default=DEFAULT_LOCALE,
)


_MESSAGES: dict[Locale, dict[str, str]] = {
    "ja": {
        "common.login_required": "ログインが必要です",
        "common.invalid_json": "JSON形式が不正です。",
        "common.internal_error": "内部エラーが発生しました。",
        "preferences.invalid_locale": "対応していない言語です。",
        "preferences.user_not_found": "ユーザーが見つかりません。",
        "preferences.load_failed": "言語設定の取得に失敗しました。",
        "preferences.update_failed": "言語設定の更新に失敗しました。",
    },
    "en": {
        "common.login_required": "Login is required.",
        "common.invalid_json": "The JSON payload is invalid.",
        "common.internal_error": "An internal server error occurred.",
        "preferences.invalid_locale": "This language is not supported.",
        "preferences.user_not_found": "The user could not be found.",
        "preferences.load_failed": "Failed to load the language preference.",
        "preferences.update_failed": "Failed to update the language preference.",
    },
}


# 完全一致する既知のシステム文言だけを翻訳する。ユーザー入力を部分一致で変換しない。
# Translate only exact known system strings; never transform user content by substring.
_ENGLISH_BY_JAPANESE_TEXT: dict[str, str] = {
    "ログインが必要です": "Login is required.",
    "ログインが必要です。": "Login is required.",
    "JSON形式が不正です。": "The JSON payload is invalid.",
    "内部エラーが発生しました。": "An internal server error occurred.",
    "サーバー内部でエラーが発生しました。": "An internal server error occurred.",
    "対応していない言語です。": "This language is not supported.",
    "ユーザーが見つかりません。": "The user could not be found.",
    "言語設定の取得に失敗しました。": "Failed to load the language preference.",
    "言語設定の更新に失敗しました。": "Failed to update the language preference.",
    "該当ルームが見つかりません": "The requested chat room could not be found.",
    "共有リンクが見つかりません": "The shared link could not be found.",
    "共有対象のメモが見つかりません。": "The memo to share could not be found.",
    "プロンプト一覧のカーソルが不正です。": "The prompt feed cursor is invalid.",
    "プロンプト一覧の絞り込み条件が不正です。": "The prompt feed filter is invalid.",
    "該当するコンテキストが見つかりません。": "The requested context could not be found.",
    "他の場所で先に更新されました。最新の内容を読み込み直してからやり直してください。": (
        "This context was updated elsewhere. Reload the latest version and try again."
    ),
    "インポート形式が不正です。": "The import format is invalid.",
    "エクスポート形式が不正です。": "The export format is invalid.",
}


def normalize_locale(value: Any, *, default: Locale | None = None) -> Locale | None:
    """Normalize a supported BCP 47 language tag to the application's base locale."""
    if not isinstance(value, str):
        return default
    language = value.strip().lower().replace("_", "-").split("-", 1)[0]
    if language in SUPPORTED_LOCALES:
        return language  # type: ignore[return-value]
    return default


def parse_accept_language(value: str | None) -> Locale:
    """Resolve the best supported locale from an Accept-Language header."""
    if not value:
        return DEFAULT_LOCALE

    candidates: list[tuple[float, int, Locale]] = []
    for index, item in enumerate(value.split(",")):
        parts = [part.strip() for part in item.split(";")]
        locale = normalize_locale(parts[0])
        if locale is None:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            if not parameter.lower().startswith("q="):
                continue
            try:
                quality = float(parameter[2:])
            except ValueError:
                quality = 0.0
            break
        if quality > 0:
            candidates.append((min(quality, 1.0), -index, locale))

    if not candidates:
        return DEFAULT_LOCALE
    return max(candidates)[2]


def get_current_locale() -> Locale:
    return _current_locale.get()


def set_current_locale(locale: Any):
    """Set the request locale and return the ContextVar token for optional resetting."""
    return _current_locale.set(normalize_locale(locale, default=DEFAULT_LOCALE))


def reset_current_locale(token: Any) -> None:
    _current_locale.reset(token)


def get_request_locale(request: Request) -> Locale:
    state_locale = normalize_locale(getattr(request.state, "locale", None))
    if state_locale is not None:
        return state_locale

    session = request.scope.get("session")
    if isinstance(session, dict):
        session_locale = normalize_locale(session.get(PREFERRED_LOCALE_SESSION_KEY))
        if session_locale is not None:
            return session_locale

    cookie_locale = normalize_locale(request.cookies.get(LOCALE_COOKIE_NAME))
    if cookie_locale is not None:
        return cookie_locale
    return parse_accept_language(request.headers.get("accept-language"))


# 日本語: 応答言語をユーザーの入力言語へ合わせるための共通ルールを組み立てます。
# English: Build the shared rules that bind the reply language to the user's input language.
def build_response_language_policy(locale: Any = None) -> str:
    """Return the response-language rules, including how to resolve mixed-language input.

    The saved interface locale is only the last-resort fallback: the reply language is
    decided from the user's own text first.
    """
    resolved_locale = normalize_locale(locale, default=DEFAULT_LOCALE) or DEFAULT_LOCALE
    fallback_language = "English" if resolved_locale == "en" else "Japanese"
    return "\n".join(
        [
            "Match the reply to the language of the user's input text: write the whole reply in "
            "the language of the user's latest substantive message.",
            "An explicit language request from the user takes priority over everything else, even "
            "when that request is written in another language.",
            "When a single message mixes languages (Japanese and English, for example), decide the "
            "reply language in this order:",
            "1. Use the language of the part that states the user's request or instruction - what "
            "they are asking you to do. It outweighs quoted text, pasted logs, code, error "
            "messages, file contents, and proper nouns.",
            "2. If the request itself is mixed, use the language that accounts for the larger share "
            "of the text the user wrote.",
            "3. If it is still ambiguous, follow the language the user used earlier in this "
            f"conversation, and only then fall back to the saved interface language ({fallback_language}).",
            "Keep one language throughout a single reply. Technical terms, product names, and code "
            "identifiers may stay in their original form and do not count as a language switch.",
            "Do not translate user-authored content unless the user asks you to.",
        ]
    )


# 日本語: 非LLMの短いフォールバック文言用に、依頼部分を優先してユーザー入力の主な言語を推定します。
# English: Infer the main language of user text for short non-LLM fallback messages, prioritizing the request portion.
def infer_response_language(text: Any, locale: Any = None) -> Locale:
    normalized = str(text or "")
    request_lines = [
        line for line in normalized.splitlines() if _JAPANESE_REQUEST_PATTERN.search(line)
    ]
    if not request_lines:
        request_lines = [
            line for line in normalized.splitlines() if _ENGLISH_REQUEST_PATTERN.search(line)
        ]
    if request_lines:
        normalized = request_lines[0]
    japanese_characters = sum(
        1
        for character in normalized
        if "\u3040" <= character <= "\u30ff" or "\u3400" <= character <= "\u9fff"
    )
    english_characters = sum(character.isascii() and character.isalpha() for character in normalized)
    if japanese_characters > english_characters:
        return "ja"
    if english_characters > japanese_characters:
        return "en"
    return normalize_locale(locale, default=DEFAULT_LOCALE) or DEFAULT_LOCALE


def translate(message_key: str, locale: Any = None, **params: Any) -> str:
    resolved_locale = normalize_locale(locale, default=get_current_locale())
    template = _MESSAGES.get(resolved_locale, {}).get(message_key)
    if template is None:
        template = _MESSAGES[DEFAULT_LOCALE].get(message_key, message_key)
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, ValueError):
        return template


def translate_text(value: Any, locale: Any = None) -> Any:
    """Translate a known exact Japanese system string, preserving all other values."""
    if not isinstance(value, str):
        return value
    resolved_locale = normalize_locale(locale, default=get_current_locale())
    if resolved_locale != "en":
        return value
    return _ENGLISH_BY_JAPANESE_TEXT.get(value, value)
