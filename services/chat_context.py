from __future__ import annotations

import html
import math
import re

_HTML_BR_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
_REFERENCE_CONTEXT_START_PATTERN = re.compile(
    r"\A<(?:fetched_urls|attached_files)(?:\s[^>]*)?>",
    re.IGNORECASE,
)
_REFERENCE_CONTEXT_BOUNDARY_PATTERN = re.compile(
    r"(?P<closing></(?:fetched_urls|attached_files)>)[ \t]*\n[ \t]*\n",
    re.IGNORECASE,
)

# This is an application input budget, not an LLM provider context-window limit.
# It deliberately leaves sufficient room for the fixed product prompt and a
# complete recent turn. Provider-specific APIs remain the final authority on
# their full request-window limits.
CONTEXT_TOKEN_BUDGET = 12000
SUMMARY_TOKEN_BUDGET = 900
MEMORY_TOKEN_BUDGET = 500
RECENT_HISTORY_TOKEN_BUDGET = 3400
PROJECT_INSTRUCTIONS_TOKEN_BUDGET = 1200
USER_PROFILE_TOKEN_BUDGET = 1000
TASK_PROMPT_TOKEN_BUDGET = 1200
RECENT_HISTORY_MAX_MESSAGES = 16
GUARANTEED_RECENT_MESSAGE_COUNT = 3
ARCHIVE_RECENT_MESSAGE_COUNT = 12
ARCHIVE_RECENT_TOKEN_BUDGET = RECENT_HISTORY_TOKEN_BUDGET
ARCHIVE_SUMMARY_MAX_ITEMS = 4
ARCHIVE_SUMMARY_ITEM_TOKENS = 120

# 小型モデルでも生成UIの要否判定と構造化出力を最後まで実行できるよう、
# 可変コンテキストの後ろに置く短い最終契約。詳細仕様と few-shot はベース
# プロンプトに残し、ここでは実行条件と完了条件だけを再提示する。
# Compact final contract placed after variable system context so smaller models
# reliably make the UI decision and finish the structured output. Detailed rules
# and few-shot examples remain in the base prompt; this repeats only execution
# and completion criteria.
# 日本語: 生成UIの出力要否、Artifact形式、完了条件だけを最終出力前に再確認させる実行契約プロンプト。
GENERATIVE_UI_EXECUTION_CONTRACT = """
<generative_ui_execution_contract>
This is the final output contract to apply right before you answer. Internally choose one UI_MODE from NONE / 2D / 3D, and never output UI_MODE itself.

Decision order:
1. NONE by default, including comparisons, flows, hierarchies, calculations, procedures, and explanations.
2. NONE when the user asked for "text only", "no UI", or "no diagrams".
3. 3D only when the latest user request explicitly asks for 3D, solid shapes, spatial models, orbits, or a rotation demo.
4. 2D only when the latest user request explicitly asks for generative UI, a visualization, a diagram, a chart, a flow, a timeline, or an interactive demo.

When UI_MODE is 2D or 3D:
- Always output exactly one complete ```chatcore-artifact fenced block right after a short introduction. An answer that ends with explanation alone is incomplete.
- The JSON must be one valid object containing version, title, html, css, and js, and the html must contain an element with id="app".
- For 3D, always include "libraries":["three"], and finish it with the core features of THREE only, without external URLs or add-ons.
- Do not explain the HTML, CSS, and JavaScript in separate code blocks instead of producing an Artifact.
- Before sending, confirm that the closing brace and closing fence are present, that the initial render is not empty, and that newlines and quotes inside JSON strings are escaped correctly.
</generative_ui_execution_contract>
""".strip()


# テキストのトークン数を概算（簡易見積もり）する
# Roughly estimate the token count of a given text
def estimate_token_count(text: str) -> int:
    normalized = text if isinstance(text, str) else str(text)
    if not normalized:
        return 0
    # 4文字あたり約1トークンとして計算
    # Calculate roughly as 1 token per 4 characters
    return max(1, math.ceil(len(normalized) / 4))


# メッセージテキストをクレンジングして正規化する
# Clean and normalize the message text
def normalize_message_text(text: str) -> str:
    normalized = text if isinstance(text, str) else str(text)
    # HTML実体参照のデコードと改行・空白の整理
    # Decode HTML entities and organize newlines/spaces
    normalized = html.unescape(normalized)
    normalized = _HTML_BR_PATTERN.sub("\n", normalized)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized)
    normalized = _BLANK_LINES_PATTERN.sub("\n\n", normalized)
    return normalized.strip()


# トークン上限に収まるようにテキストを切り詰める
# Trim the text to fit within the specified token budget
def trim_text_to_token_budget(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    normalized = normalize_message_text(text)
    # 既に予算内に収まっていればそのまま返す
    # Return directly if it is already within the budget
    if estimate_token_count(normalized) <= max_tokens:
        return normalized

    # 切り詰め後の文字数を算出して末尾に省略記号を付与する
    # Calculate truncated character count and append ellipsis
    max_chars = max_tokens * 4
    if max_chars <= 3:
        return normalized[:max_chars]
    return normalized[: max_chars - 3].rstrip() + "..."


def _trim_user_text_preserving_trailing_request(text: str, max_tokens: int) -> str:
    """Keep both the subject and trailing constraints in an oversized user turn."""
    normalized = normalize_message_text(text)
    if estimate_token_count(normalized) <= max_tokens:
        return normalized

    max_chars = max_tokens * 4
    if max_chars <= 6:
        return normalized[-max_chars:]

    # Long pasted material often ends with the actual question, requested
    # format, or an exception. Preserve that tail while keeping a small leading
    # slice so the request still has a subject.
    omission_marker = "\n…\n"
    tail_chars = max(1, int((max_chars - len(omission_marker)) * 0.7))
    head_chars = max_chars - len(omission_marker) - tail_chars
    if head_chars <= 0:
        return normalized[-max_chars:]
    return (
        normalized[:head_chars].rstrip()
        + omission_marker
        + normalized[-tail_chars:].lstrip()
    )


def _split_leading_reference_context(text: str) -> tuple[str, str] | None:
    """Split generated reference prefixes from the user's trailing request."""
    normalized = normalize_message_text(text)
    if not _REFERENCE_CONTEXT_START_PATTERN.match(normalized):
        return None

    # URL and attachment blocks are generated before the actual user request and
    # separated from it by a blank line. Use the final generated block boundary so
    # a turn containing both blocks keeps them together as reference context.
    boundaries = list(_REFERENCE_CONTEXT_BOUNDARY_PATTERN.finditer(normalized))
    if not boundaries:
        return None
    boundary = boundaries[-1]
    reference_context = normalized[: boundary.end("closing")].strip()
    user_request = normalized[boundary.end() :].strip()
    if not reference_context or not user_request:
        return None
    return reference_context, user_request


def _trim_latest_message_to_token_budget(
    content: str,
    role: str,
    max_tokens: int,
) -> str:
    """Trim the newest message while preserving a trailing user request first."""
    normalized_content = normalize_message_text(content)
    if estimate_token_count(normalized_content) <= max_tokens:
        return normalized_content
    if role != "user":
        return trim_text_to_token_budget(normalized_content, max_tokens)

    split_content = _split_leading_reference_context(normalized_content)
    if split_content is None:
        return _trim_user_text_preserving_trailing_request(normalized_content, max_tokens)

    reference_context, user_request = split_content
    request_tokens = estimate_token_count(user_request)
    if request_tokens >= max_tokens:
        return _trim_user_text_preserving_trailing_request(user_request, max_tokens)

    separator = "\n\n"
    reference_budget = max_tokens - request_tokens - estimate_token_count(separator)
    if reference_budget <= 0:
        return user_request

    trimmed_reference = trim_text_to_token_budget(reference_context, reference_budget)
    if not trimmed_reference:
        return user_request
    return f"{trimmed_reference}{separator}{user_request}"


# 会話履歴の古いメッセージから、要約情報（XML形式）を作成する
# Build a summary (XML format) from the older messages in the conversation history
def build_room_summary(messages: list[dict[str, str]]) -> tuple[str, int]:
    # Keep a recent window by both message count and token size. A generated UI
    # or other long answer can exhaust the history budget in only a few turns,
    # so message count alone is not sufficient to decide when to summarize.
    if len(messages) <= 2:
        return "", 0

    total_tokens = sum(estimate_token_count(message.get("content", "")) for message in messages)
    if len(messages) <= ARCHIVE_RECENT_MESSAGE_COUNT and total_tokens <= ARCHIVE_RECENT_TOKEN_BUDGET:
        return "", 0

    recent_start = len(messages)
    recent_count = 0
    recent_tokens = 0
    for index in range(len(messages) - 1, -1, -1):
        message_tokens = estimate_token_count(messages[index].get("content", ""))
        # Always retain the latest pair. Older messages are retained only while
        # they fit the rolling token window.
        if recent_count >= 2 and (
            recent_count >= ARCHIVE_RECENT_MESSAGE_COUNT
            or recent_tokens + message_tokens > ARCHIVE_RECENT_TOKEN_BUDGET
        ):
            break
        recent_start = index
        recent_count += 1
        recent_tokens += message_tokens

    archived_messages = messages[:recent_start]
    if not archived_messages:
        return "", 0

    first_user_message = ""
    user_points: list[str] = []
    assistant_points: list[str] = []

    # 古いメッセージを走査して主要なポイントを抽出する
    # Iterate through archived messages and extract main points
    for message in archived_messages:
        role = str(message.get("role", "user"))
        content = trim_text_to_token_budget(
            message.get("content", ""),
            ARCHIVE_SUMMARY_ITEM_TOKENS,
        )
        if not content:
            continue

        if role == "user":
            if not first_user_message:
                first_user_message = content
            if content not in user_points:
                user_points.append(content)
        elif role == "assistant" and content not in assistant_points:
            assistant_points.append(content)

    user_points = user_points[-ARCHIVE_SUMMARY_MAX_ITEMS:]
    assistant_points = assistant_points[-ARCHIVE_SUMMARY_MAX_ITEMS:]

    # XML形式で要約コンテキストを構築する
    # Build the summary context in XML format
    sections: list[str] = ["<conversation_summary>"]
    sections.append(
        f"<archived_message_count>{len(archived_messages)}</archived_message_count>"
    )
    if first_user_message:
        sections.extend(
            [
                "<original_goal>",
                first_user_message,
                "</original_goal>",
            ]
        )
    if user_points:
        sections.append("<user_points>")
        for point in user_points:
            sections.append(f"- {point}")
        sections.append("</user_points>")
    if assistant_points:
        sections.append("<assistant_points>")
        for point in assistant_points:
            sections.append(f"- {point}")
        sections.append("</assistant_points>")
    sections.append(
        "<summary_instruction>The summary above is compressed information from older history. "
        "When it conflicts with the most recent messages, prioritize the recent messages."
        "</summary_instruction>"
    )
    sections.append("</conversation_summary>")
    summary = "\n".join(section for section in sections if section).strip()
    return trim_text_to_token_budget(summary, SUMMARY_TOKEN_BUDGET), len(archived_messages)


# トークン予算と上限メッセージ数に収まる範囲で、直近のメッセージを後ろから順に選択する
# Select recent messages from the end, fitting within the token budget and maximum message limit
def select_recent_messages(
    messages: list[dict[str, str]],
    token_budget: int,
    *,
    max_messages: int = RECENT_HISTORY_MAX_MESSAGES,
) -> list[dict[str, str]]:
    if token_budget <= 0 or max_messages <= 0:
        return []

    normalized_messages = [
        {
            "role": str(message.get("role", "user")),
            "content": normalize_message_text(message.get("content", "")),
        }
        for message in messages
    ]
    normalized_messages = [message for message in normalized_messages if message["content"]]
    if not normalized_messages:
        return []

    selected_reversed: list[dict[str, str]] = []
    remaining_tokens = token_budget

    # Include the newest message first and retain a compact representation of
    # the two preceding messages. Allocating that window up front prevents one
    # long assistant answer from dropping the user instruction that it answers.
    newest = normalized_messages[-1]
    newest_content = _trim_latest_message_to_token_budget(
        newest["content"], newest["role"], remaining_tokens
    )
    if not newest_content:
        return []
    selected_reversed.append({"role": newest["role"], "content": newest_content})
    remaining_tokens -= estimate_token_count(newest_content)

    guaranteed_count = min(
        GUARANTEED_RECENT_MESSAGE_COUNT,
        max_messages,
        len(normalized_messages),
    )
    guaranteed_messages = list(reversed(normalized_messages[-guaranteed_count:-1]))
    for offset, message in enumerate(guaranteed_messages):
        if remaining_tokens <= 0:
            break
        slots_remaining = len(guaranteed_messages) - offset
        allocation = max(1, math.ceil(remaining_tokens / slots_remaining))
        content = trim_text_to_token_budget(message["content"], allocation)
        if not content:
            continue
        selected_reversed.append({"role": message["role"], "content": content})
        remaining_tokens -= estimate_token_count(content)

    # Fill the remaining capacity with older history. If a message is too large,
    # preserve a bounded version and keep walking instead of terminating early.
    older_end = max(0, len(normalized_messages) - guaranteed_count)
    for message in reversed(normalized_messages[:older_end]):
        if len(selected_reversed) >= max_messages or remaining_tokens <= 0:
            break
        content = trim_text_to_token_budget(message["content"], remaining_tokens)
        if not content:
            continue
        selected_reversed.append({"role": message["role"], "content": content})
        remaining_tokens -= estimate_token_count(content)

    return list(reversed(selected_reversed))


# 会話の古い要約をシステムプロンプトのフォーマットで構築する
# Build the system message containing the archived summary
def build_summary_system_message(summary_text: str) -> dict[str, str] | None:
    if not summary_text:
        return None
    trimmed = trim_text_to_token_budget(summary_text, SUMMARY_TOKEN_BUDGET)
    if not trimmed:
        return None
    # 日本語: 古い会話の要約を最新ターンより優先しない参照用文脈として渡すシステムプロンプト。
    return {
        "role": "system",
        "content": (
            "<archived_context>\n"
            "The following is a compressed summary of older conversation history. Use it to carry "
            "over facts and constraints, and do not prioritize it over the most recent turns.\n"
            f"{trimmed}\n"
            "</archived_context>"
        ),
    }


# メモリ・ファクトリストをシステムメッセージの形式で構築する
# Build the system message representing the memory facts list
def build_memory_system_message(memory_facts: list[str]) -> dict[str, str] | None:
    normalized_facts = [
        trim_text_to_token_budget(fact, 80)
        for fact in memory_facts
        if trim_text_to_token_budget(fact, 80)
    ]
    if not normalized_facts:
        return None

    # 日本語: ユーザーの情報・好みを会話を通じて尊重するよう渡すシステムプロンプト。
    sections = [
        "<memory_facts>",
        "The following is user information or preferences you must keep honoring throughout this "
        "conversation.",
    ]
    # ファクト項目を箇条書きで追加する
    # Append fact entries as bullet points
    for fact in normalized_facts:
        sections.append(f"- {fact}")
    sections.append("</memory_facts>")
    content = "\n".join(sections)
    return {
        "role": "system",
        "content": trim_text_to_token_budget(content, MEMORY_TOKEN_BUDGET),
    }


# プロジェクト（ChatGPT/Claude のプロジェクトに相当）のカスタム指示をシステムメッセージ化する
# Build the system message carrying a project's custom instructions.
def build_project_instructions_message(instructions: str | None) -> dict[str, str] | None:
    if not instructions:
        return None
    trimmed = trim_text_to_token_budget(instructions, PROJECT_INSTRUCTIONS_TOKEN_BUDGET)
    if not trimmed:
        return None
    # 日本語: プロジェクト固有の指示を当該プロジェクト内の会話で優先するよう渡すシステムプロンプト。
    return {
        "role": "system",
        "content": (
            "<project_instructions>\n"
            "The following are instructions specific to this project. Follow them with priority in "
            "every conversation inside the project.\n"
            f"{trimmed}\n"
            "</project_instructions>"
        ),
    }


# ベース指示、ユーザー定義、タスク指示、要約、メモリ、直近履歴を統合したLLM送信用メッセージリストを構築する
# Build the list of messages for LLM request by integrating base instruction, user info, task context, summary, memory, and recent history
def build_context_messages(
    *,
    base_system_prompt: str,
    user_profile_prompt: str | None,
    task_prompt: str | None,
    room_summary: str,
    memory_facts: list[str],
    recent_messages: list[dict[str, str]],
    project_instructions: str | None = None,
) -> list[dict[str, str]]:
    mandatory_messages = [
        {"role": "system", "content": base_system_prompt},
        {"role": "system", "content": GENERATIVE_UI_EXECUTION_CONTRACT},
    ]
    mandatory_tokens = sum(
        estimate_token_count(str(message.get("content", "")))
        for message in mandatory_messages
    )
    # Reserve the recent-history window before optional system context. This
    # keeps prior turns available even when a project or task has long guidance.
    reserved_history_tokens = min(
        RECENT_HISTORY_TOKEN_BUDGET,
        max(CONTEXT_TOKEN_BUDGET - mandatory_tokens, 0),
    )
    optional_tokens_remaining = max(
        CONTEXT_TOKEN_BUDGET - mandatory_tokens - reserved_history_tokens,
        0,
    )
    optional_messages: list[dict[str, str]] = []

    def append_optional_system_message(content: str | None, limit: int) -> None:
        nonlocal optional_tokens_remaining
        if not content or optional_tokens_remaining <= 0:
            return
        allowed_tokens = min(limit, optional_tokens_remaining)
        trimmed = trim_text_to_token_budget(content, allowed_tokens)
        if not trimmed:
            return
        optional_messages.append({"role": "system", "content": trimmed})
        optional_tokens_remaining -= estimate_token_count(trimmed)

    # ユーザープロフィールプロンプトを追加
    # Add user profile prompt if specified
    append_optional_system_message(user_profile_prompt, USER_PROFILE_TOKEN_BUDGET)

    # プロジェクト固有のカスタム指示を追加（タスク指示より前に置き全会話で優先）
    # Add project custom instructions (before task prompt; applies to all chats in the project)
    project_instructions_message = build_project_instructions_message(project_instructions)
    if project_instructions_message is not None:
        append_optional_system_message(
            project_instructions_message["content"], PROJECT_INSTRUCTIONS_TOKEN_BUDGET
        )

    # タスクテンプレートプロンプトを追加
    # Add task template prompt if specified
    append_optional_system_message(task_prompt, TASK_PROMPT_TOKEN_BUDGET)

    # 履歴要約メッセージを追加
    # Add history summary message if it exists
    summary_message = build_summary_system_message(room_summary)
    if summary_message is not None:
        append_optional_system_message(summary_message["content"], SUMMARY_TOKEN_BUDGET)

    # 永続メモリファクトメッセージを追加
    # Add persistent memory facts message if it exists
    memory_message = build_memory_system_message(memory_facts)
    if memory_message is not None:
        append_optional_system_message(memory_message["content"], MEMORY_TOKEN_BUDGET)

    # タスク・プロフィール・プロジェクト指示などの可変システム文脈を読んだ後に、
    # 生成UIの完了条件を短く再提示する。OpenAI Responses APIでは developer
    # message、Claude APIでは先頭のsystem promptとして同じ位置関係を保つ。
    # Re-state the generative UI completion criteria after variable system
    # context. This becomes a developer message for OpenAI Responses and remains
    # a system prompt for the Claude API.
    messages = [mandatory_messages[0], *optional_messages, mandatory_messages[1]]

    # システムメッセージ群で使用されたトークン数を算出して直近履歴に使えるトークン予算を決定する
    # Calculate tokens used by system messages to determine the remaining budget for recent history
    reserved_tokens = sum(
        estimate_token_count(str(message.get("content", "")))
        for message in messages
    )
    remaining_tokens = min(CONTEXT_TOKEN_BUDGET - reserved_tokens, reserved_history_tokens)
    if remaining_tokens < 0:
        remaining_tokens = 0

    # 予算内で直近のメッセージを追加する
    # Extend the messages with recent items within the calculated budget
    messages.extend(select_recent_messages(recent_messages, remaining_tokens))
    return messages
