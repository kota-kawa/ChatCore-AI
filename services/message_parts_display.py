# アシスタントメッセージのパーツ（テキスト／生成UI／Web検索画像）の表示順を決める。
# 生成UIとWeb検索画像は1ターン内で排他であり、画像は「回答までのステップ」
# （回答トレース）の直下・本文の上に置く。1回答あたりの画像数もここで制限する。
# Owns the display ordering contract for assistant message parts (text /
# generated UI / web-search images). A generated UI and web-search images are
# mutually exclusive within one turn, and images belong directly below the
# answer-trace block ("回答までのステップ") and above the explanation.

from __future__ import annotations

import re
from typing import Any

# 生成UIとして同じ視覚スロットを占めるパーツ種別。
# Part types that occupy the generated-UI visual slot.
GENERATIVE_UI_PART_TYPES = frozenset({"sandbox_artifact", "interactive_buttons"})
WEB_SEARCH_IMAGE_PART_TYPE = "web_search_image"
TEXT_PART_TYPE = "text"
MAX_WEB_SEARCH_IMAGES_PER_REPLY = 5

# 回答トレース（「回答までのステップ」）ブロックのルート要素クラス。
# web_search_trace.py の組み立てと、ここでの分割で同じ定義を共有する。
# The root element class of the answer-trace block, shared between the builder in
# web_search_trace.py and the split performed here.
ANSWER_TRACE_DETAILS_CLASS = "web-search-sources web-search-sources--trace"
_TRACE_BLOCK_START = f'<details class="{ANSWER_TRACE_DETAILS_CLASS}"'
# トレース内部にもステップ用の <details> が入れ子になるため、開閉を数えて末尾を探す。
# Steps nest their own <details>, so the block end is found by counting tags.
_DETAILS_TAG_RE = re.compile(r"<details\b|</details\s*>", re.IGNORECASE)


def split_answer_trace_block(text: str) -> tuple[str, str]:
    """Split a leading answer-trace block off ``text``.

    Returns ``(trace_block, remaining_text)``. When the text does not start with
    a trace block, the trace is ``""`` and the text is returned unchanged.
    """
    if not isinstance(text, str) or not text:
        return "", text if isinstance(text, str) else ""
    stripped = text.lstrip()
    if not stripped.startswith(_TRACE_BLOCK_START):
        return "", text
    offset = len(text) - len(stripped)
    depth = 0
    for match in _DETAILS_TAG_RE.finditer(stripped):
        depth += 1 if match.group().lower().startswith("<details") else -1
        if depth:
            continue
        end = offset + match.end()
        return text[:end], text[end:].lstrip("\n")
    return "", text


def apply_visual_part_contract(parts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Enforce visual exclusivity and keep images above the explanation.

    A generated UI wins over web-search images. Without a generated UI, images move
    ahead of the prose so they never become a trailing footer, and only the first
    five images are retained. The trace-aware placement is applied later by
    :func:`normalize_message_parts_for_display`.
    """
    normalized = [part for part in (parts or []) if isinstance(part, dict)]
    if any(part.get("type") in GENERATIVE_UI_PART_TYPES for part in normalized):
        return [part for part in normalized if part.get("type") != WEB_SEARCH_IMAGE_PART_TYPE]

    image_parts = [
        part
        for part in normalized
        if part.get("type") == WEB_SEARCH_IMAGE_PART_TYPE
    ][:MAX_WEB_SEARCH_IMAGES_PER_REPLY]
    other_parts = [part for part in normalized if part.get("type") != WEB_SEARCH_IMAGE_PART_TYPE]
    return [*image_parts, *other_parts]


def normalize_message_parts_for_display(
    parts: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Apply the display contract without re-validating payloads.

    On top of :func:`apply_visual_part_contract`, a leading answer-trace block is
    split into its own text part so the web-search images render below
    「回答までのステップ」 instead of above it. Payload validation remains the
    responsibility of ``services.generative_ui._decode_message_parts``.
    """
    contracted = apply_visual_part_contract(parts)
    image_parts = [part for part in contracted if part.get("type") == WEB_SEARCH_IMAGE_PART_TYPE]
    if not image_parts:
        return contracted

    other_parts = [part for part in contracted if part.get("type") != WEB_SEARCH_IMAGE_PART_TYPE]
    head = other_parts[0] if other_parts else None
    trace, remainder = ("", "")
    if head is not None and head.get("type") == TEXT_PART_TYPE:
        trace, remainder = split_answer_trace_block(head.get("text") or "")
    if not trace:
        return [*image_parts, *other_parts]

    body_parts = [{**head, "text": remainder}] if remainder.strip() else []
    return [{**head, "text": trace}, *image_parts, *body_parts, *other_parts[1:]]
