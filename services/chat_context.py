from __future__ import annotations

import html
import math
import re

_HTML_BR_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")

CONTEXT_TOKEN_BUDGET = 6000
SUMMARY_TOKEN_BUDGET = 900
MEMORY_TOKEN_BUDGET = 500
RECENT_HISTORY_TOKEN_BUDGET = 3400
PROJECT_INSTRUCTIONS_TOKEN_BUDGET = 1200
RECENT_HISTORY_MAX_MESSAGES = 16
ARCHIVE_RECENT_MESSAGE_COUNT = 12
ARCHIVE_SUMMARY_MAX_ITEMS = 4
ARCHIVE_SUMMARY_ITEM_TOKENS = 120

# 小型モデルでも生成UIの要否判定と構造化出力を最後まで実行できるよう、
# 可変コンテキストの後ろに置く短い最終契約。詳細仕様と few-shot はベース
# プロンプトに残し、ここでは実行条件と完了条件だけを再提示する。
# Compact final contract placed after variable system context so smaller models
# reliably make the UI decision and finish the structured output. Detailed rules
# and few-shot examples remain in the base prompt; this repeats only execution
# and completion criteria.
GENERATIVE_UI_EXECUTION_CONTRACT = """
<generative_ui_execution_contract>
これは回答直前に適用する最終出力契約です。内部で UI_MODE を NONE / 2D / 3D から1つ選び、UI_MODE 自体は出力しないでください。

判定順序:
1. ユーザーが「テキストだけ」「UI不要」「図は不要」と指定した場合は NONE。
2. ユーザーが3D、立体、空間モデル、軌道、回転デモを明示的に求めた場合は 3D。
3. ユーザーが生成UI、可視化、図解、チャート、フロー、タイムライン、操作可能なデモを明示的に求めた場合は 2D（空間理解が中心なら3D）。
4. 明示がなくても、比較・流れ・階層・位置関係・割合・優先度・状態・因果・入力による変化をUIにすると理解が明確になる場合は 2D または 3D。それ以外は NONE。

UI_MODE が 2D または 3D の場合:
- 短い導入文の直後に、完全な ```chatcore-artifact fenced block を必ず1つ出力してください。説明文だけで終える回答は未完了です。
- JSONは version、title、html、css、js を含む有効な1オブジェクトとし、htmlには id="app" の要素を含めてください。
- 3Dでは必ず "libraries":["three"] を含め、外部URLやアドオンを使わず THREE のコア機能だけで完成させてください。
- Artifactの代わりにHTML・CSS・JavaScriptを別々のコードブロックで説明しないでください。
- 送信前に、閉じ波括弧と閉じフェンスまで存在し、初期表示が空でなく、JSON文字列の改行・引用符が正しくエスケープされていることを確認してください。
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


# 会話履歴の古いメッセージから、要約情報（XML形式）を作成する
# Build a summary (XML format) from the older messages in the conversation history
def build_room_summary(messages: list[dict[str, str]]) -> tuple[str, int]:
    # 直近のメッセージ数以下の場合は要約を行わない
    # Do not summarize if history size is below the recent message count threshold
    if len(messages) <= ARCHIVE_RECENT_MESSAGE_COUNT:
        return "", 0

    archived_messages = messages[:-ARCHIVE_RECENT_MESSAGE_COUNT]
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
        "<summary_instruction>上の要約は古い履歴の圧縮情報です。直近メッセージと矛盾する場合は直近メッセージを優先してください。</summary_instruction>"
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
    if token_budget <= 0:
        return []

    selected_reversed: list[dict[str, str]] = []
    remaining_tokens = token_budget

    # メッセージ履歴を後ろから前に向かって走査する
    # Iterate through the message history backwards from the end
    for message in reversed(messages):
        normalized_content = normalize_message_text(message.get("content", ""))
        if not normalized_content:
            continue

        # 最初のメッセージ（一番新しいもの）は、切り詰めてでも必ず含める
        # Always include the first message (most recent one) even if it needs trimming
        if not selected_reversed:
            trimmed_content = trim_text_to_token_budget(normalized_content, remaining_tokens)
            if not trimmed_content:
                continue
            selected_reversed.append(
                {
                    "role": str(message.get("role", "user")),
                    "content": trimmed_content,
                }
            )
            remaining_tokens -= estimate_token_count(trimmed_content)
            continue

        # メッセージ数制限またはトークン制限に達した場合は走査を終了する
        # Terminate traversal if limits on message count or token budget are met
        if len(selected_reversed) >= max_messages or remaining_tokens <= 0:
            break

        message_tokens = estimate_token_count(normalized_content)
        if message_tokens > remaining_tokens:
            break

        selected_reversed.append(
            {
                "role": str(message.get("role", "user")),
                "content": normalized_content,
            }
        )
        remaining_tokens -= message_tokens

    return list(reversed(selected_reversed))


# 会話の古い要約をシステムプロンプトのフォーマットで構築する
# Build the system message containing the archived summary
def build_summary_system_message(summary_text: str) -> dict[str, str] | None:
    if not summary_text:
        return None
    trimmed = trim_text_to_token_budget(summary_text, SUMMARY_TOKEN_BUDGET)
    if not trimmed:
        return None
    return {
        "role": "system",
        "content": (
            "<archived_context>\n"
            "以下は古い会話履歴の圧縮要約です。事実・制約の引き継ぎに使い、直近ターンより優先しないでください。\n"
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

    sections = [
        "<memory_facts>",
        "以下はこの会話で継続的に守るべきユーザー情報または設定です。",
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
    return {
        "role": "system",
        "content": (
            "<project_instructions>\n"
            "以下はこのプロジェクト固有の指示です。プロジェクト内の全会話で優先して従ってください。\n"
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
    messages = [{"role": "system", "content": base_system_prompt}]

    # ユーザープロフィールプロンプトを追加
    # Add user profile prompt if specified
    if user_profile_prompt:
        messages.append({"role": "system", "content": user_profile_prompt})

    # プロジェクト固有のカスタム指示を追加（タスク指示より前に置き全会話で優先）
    # Add project custom instructions (before task prompt; applies to all chats in the project)
    project_instructions_message = build_project_instructions_message(project_instructions)
    if project_instructions_message is not None:
        messages.append(project_instructions_message)

    # タスクテンプレートプロンプトを追加
    # Add task template prompt if specified
    if task_prompt:
        messages.append({"role": "system", "content": task_prompt})

    # 履歴要約メッセージを追加
    # Add history summary message if it exists
    summary_message = build_summary_system_message(room_summary)
    if summary_message is not None:
        messages.append(summary_message)

    # 永続メモリファクトメッセージを追加
    # Add persistent memory facts message if it exists
    memory_message = build_memory_system_message(memory_facts)
    if memory_message is not None:
        messages.append(memory_message)

    # タスク・プロフィール・プロジェクト指示などの可変システム文脈を読んだ後に、
    # 生成UIの完了条件を短く再提示する。OpenAI Responses APIでは developer
    # message、Gemini互換APIでは system messageとして同じ位置関係を保つ。
    # Re-state the generative UI completion criteria after variable system
    # context. This becomes a developer message for OpenAI Responses and remains
    # a system message for the Gemini-compatible API.
    messages.append(
        {"role": "system", "content": GENERATIVE_UI_EXECUTION_CONTRACT}
    )

    # システムメッセージ群で使用されたトークン数を算出して直近履歴に使えるトークン予算を決定する
    # Calculate tokens used by system messages to determine the remaining budget for recent history
    reserved_tokens = sum(
        estimate_token_count(str(message.get("content", "")))
        for message in messages
    )
    remaining_tokens = min(
        CONTEXT_TOKEN_BUDGET - reserved_tokens,
        RECENT_HISTORY_TOKEN_BUDGET,
    )
    if remaining_tokens < 0:
        remaining_tokens = 0

    # 予算内で直近のメッセージを追加する
    # Extend the messages with recent items within the calculated budget
    messages.extend(select_recent_messages(recent_messages, remaining_tokens))
    return messages
