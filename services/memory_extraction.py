"""記憶すべき事実の抽出 / Extraction of durable memory facts from a user message.

言語ごとの正規表現では、書き方や言語が変わるだけで抽出できなくなり、逆に
「今後はこの方針で進めます」のような単なる報告まで恒久的な好みとして拾ってしまう。
軽量モデルに判断させることで、言語に依存せず、恒久的な事実とその場限りの指示を
区別できるようにする。

Per-language regexes missed anything phrased differently or written in another
language, while simultaneously capturing plain statements as durable
preferences. Delegating the judgement to the lightweight model keeps extraction
language-agnostic and able to tell a standing preference from a one-off request.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .llm import LIGHTWEIGHT_TASK_MODEL, LlmServiceError, get_llm_json_response

logger = logging.getLogger(__name__)

MAX_MEMORY_FACT_LENGTH = 280
MAX_MEMORY_FACTS_PER_MESSAGE = 5
# 抽出器へ渡す入力の上限。長文貼り付けの本文まで読ませる必要はない。
# Cap on the extractor input; pasted material does not need to be read in full.
MEMORY_EXTRACTION_INPUT_CHARS = 4000

_MULTISPACE_PATTERN = re.compile(r"\s+")
_HTML_BR_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

# 日本語: ユーザー発話から、以後のターンでも尊重すべき恒久的な事実だけをJSONで抽出させるプロンプト。
_EXTRACTION_SYSTEM_PROMPT = """
You extract durable memory facts from a single user message in a chat assistant.

A durable memory fact is something the assistant should still honor many turns later:
- how the user wants to be addressed: name, nickname, pronouns, or title
- a standing preference for how answers should be written: language, tone, length, or format
- stable context the user states about themselves: role, team, tooling, timezone, or a constraint they work under
- anything the user explicitly asks you to remember

Never extract:
- a choice that applies only to the current turn, such as picking one of the options you just offered, or asking for this particular answer to be shorter
- the subject the user is asking about, the content of material they pasted, or facts about other people
- anything the user did not state about themselves
- a plain report of a decision or an event, when it carries no instruction about future answers

Write each fact as one short self-contained sentence, in the same language the user wrote in, phrased so it still makes sense with none of the surrounding conversation available.

Return JSON only, in the form {"facts": ["...", "..."]}. Return {"facts": []} when the message contains nothing durable. Most messages contain nothing durable.
""".strip()


# 事実テキストを正規化（トリミング、連続空白の圧縮、文字数制限）する
# Normalize a fact (trim, collapse whitespace runs, cap the length)
def normalize_fact_text(text: str) -> str:
    normalized = text if isinstance(text, str) else str(text)
    normalized = normalized.strip().replace("\r\n", "\n").replace("\r", "\n")
    normalized = _MULTISPACE_PATTERN.sub(" ", normalized)
    return normalized[:MAX_MEMORY_FACT_LENGTH].strip(" .")


def _plain_text(message: str) -> str:
    """Reduce a stored message to plain text for the extractor."""
    normalized = _HTML_BR_PATTERN.sub("\n", message or "")
    normalized = _HTML_TAG_PATTERN.sub("", normalized)
    normalized = normalized.strip()
    if len(normalized) <= MEMORY_EXTRACTION_INPUT_CHARS:
        return normalized
    return normalized[:MEMORY_EXTRACTION_INPUT_CHARS].rstrip()


def _parse_facts(raw_response: Any) -> list[str]:
    """Read the model's JSON payload into a normalized fact list."""
    payload: Any = raw_response
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            logger.warning("Memory fact extractor returned unparsable JSON.")
            return []

    if not isinstance(payload, dict):
        return []

    raw_facts = payload.get("facts")
    if not isinstance(raw_facts, list):
        return []

    facts: list[str] = []
    for raw_fact in raw_facts:
        if not isinstance(raw_fact, str):
            continue
        fact = normalize_fact_text(raw_fact)
        if fact and fact not in facts:
            facts.append(fact)
        if len(facts) >= MAX_MEMORY_FACTS_PER_MESSAGE:
            break
    return facts


# メッセージから、以後のターンでも保持すべき事実を抽出する
# Extract the facts worth carrying into later turns from a single message
def extract_memory_facts(message: str) -> list[str]:
    content = _plain_text(message if isinstance(message, str) else str(message))
    if not content:
        return []

    try:
        raw_response = get_llm_json_response(
            [
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": f"<user_message>\n{content}\n</user_message>"},
            ],
            LIGHTWEIGHT_TASK_MODEL,
        )
    except LlmServiceError:
        # 誤った事実を保存するより、抽出しないほうが安全。
        # Storing nothing is safer than storing a wrong fact.
        logger.warning("Memory fact extraction unavailable; skipping this message.", exc_info=True)
        return []
    except Exception:
        logger.exception("Unexpected error while extracting memory facts.")
        return []

    return _parse_facts(raw_response)
