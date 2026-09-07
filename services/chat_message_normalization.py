"""
LLM入力向けにチャット履歴を正規化し、タスク起動リクエストを抽出する純粋ヘルパー群です。
Pure helpers that normalize chat history for LLM input and extract task-launch requests.
"""

from __future__ import annotations

import html
import re
from typing import Any

from services.attached_files import (
    decode_attached_files_from_storage,
    format_attached_files_for_prompt,
)
from services.generative_ui import build_message_parts_context

_HTML_BR_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)


# LLMに入力するメッセージコンテンツ（HTMLタグなど）を正規化する関数
# Normalize message text representation for LLM ingestion (such as converting <br> to newlines).
def normalize_message_content_for_llm(content: str, role: str) -> str:
    """
    メッセージ内のHTML改行タグや実体参照を通常改行にデコード・正規化します。
    Normalizes message text representation for LLM ingestion.
    """
    normalized = content if isinstance(content, str) else str(content)
    if role == "user":
        normalized = html.unescape(normalized)
        normalized = _HTML_BR_PATTERN.sub("\n", normalized)
    return normalized


# LLM送信用に履歴メッセージリスト全体を正規化・整形する関数
# Format and normalize a list of message objects for LLM consumption.
def normalize_messages_for_llm(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    会話履歴全体のロールやテキストデータをLLM送信用にデコード・標準化します。
    Formats and normalizes a list of message objects for LLM consumption.
    """
    normalized_messages: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "user"))
        normalized_message: dict[str, Any] = {
            "role": role,
            "content": normalize_message_content_for_llm(message.get("content", ""), role),
        }
        # Artifact source is intentionally not replayed to the model. A compact
        # description keeps follow-up requests such as "edit that chart" grounded
        # without consuming the context window with HTML/CSS/JavaScript.
        message_parts_context = build_message_parts_context(message.get("message_parts"))
        if message_parts_context:
            normalized_message["content"] += message_parts_context
        attached_file_contents = message.get("attached_file_contents")
        if attached_file_contents:
            normalized_message["attached_file_contents"] = attached_file_contents
        normalized_messages.append(normalized_message)
    return normalized_messages


# 添付済みユーザーメッセージの先頭に添付ファイルテキスト情報を埋め込む関数
# Prepend formatted attachment representations to each user message that owns them.
def prepend_attached_files_to_user_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    履歴内の添付済みユーザーメッセージそれぞれに、参照用の添付本文を挿入します。
    Prepends reference attachment content to every user message that owns an upload.
    """
    updated_messages = list(messages)
    for index, message in enumerate(messages):
        if str(message.get("role", "")) != "user":
            continue
        attached_files = decode_attached_files_from_storage(
            message.get("attached_file_contents")
        )
        if not attached_files:
            continue
        prefix = format_attached_files_for_prompt(attached_files)
        updated_message = dict(message)
        updated_message["content"] = f"{prefix}\n\n{message.get('content', '')}"
        updated_messages[index] = updated_message
    return updated_messages


# ユーザーメッセージからタスク名と状況設定情報を抽出するパース関数
# Parse and extract task launch parameters from a user message content.
def parse_task_launch_message(message: str) -> dict[str, Any] | None:
    """
    ユーザーメッセージから「【タスク】」や「【状況・作業環境】」の定義を検索・パースします。
    Parses and extracts task launch parameters from a user message content.
    """
    # 初回タスク起動メッセージからタスク名と状況情報を抽出する
    # Extract task name and setup info from the initial task-launch payload.
    if not message:
        return None

    task_match = re.search(r"^【タスク】(?P<task>[^\n]+)", message, re.MULTILINE)
    if not task_match:
        return None

    setup_match = re.search(r"【状況・作業環境】(?P<setup>[\s\S]+)", message)
    setup_info = setup_match.group("setup").strip() if setup_match else ""
    parsed: dict[str, Any] = {
        "task": task_match.group("task").strip(),
        "setup_info": setup_info,
    }
    task_id_match = re.search(r"^【タスクID】(?P<task_id>\d+)[ \t]*$", message, re.MULTILINE)
    if task_id_match:
        task_id = int(task_id_match.group("task_id"))
        if task_id > 0:
            parsed["task_id"] = task_id
    return parsed


# メッセージ履歴から最も新しいタスク起動リクエストを検索抽出する関数
# Search and extract the most recent task launch request from conversation history.
def find_latest_task_launch_request(messages: list[dict[str, str]]) -> dict[str, Any] | None:
    """
    会話履歴を逆順でスキャンし、最も新しいユーザーメッセージからタスク起動情報を抽出します。
    Searches and extracts the most recent task launch request from conversation history.
    """
    for message in reversed(messages):
        if str(message.get("role", "")) != "user":
            continue
        parsed = parse_task_launch_message(str(message.get("content", "")))
        if parsed is not None:
            return parsed
    return None
