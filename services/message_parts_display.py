# アシスタントメッセージのパーツ（テキスト／生成UI／選択ボタン／Web検索画像）の表示順を決める。
# 生成UIとWeb検索画像は1ターン内で排他であり、画像は本文パーツの指定位置に挿入する。
# 選択ボタンは生成UIではないため、この排他に加わらず、どちらとも同じ返信に並ぶ。
# 旧形式でトレース前に保存された画像だけは「回答までのステップ」の直下へ移す。
# Owns the display ordering contract for assistant message parts (text /
# generated UI / choice buttons / web-search images). A generated UI and web-search
# images are mutually exclusive within one turn. Choice buttons are not a generated UI,
# so they take no part in that exclusivity and can sit beside either. Inline images
# preserve their authored position; legacy images before the answer trace move below it.

from __future__ import annotations

import re
from typing import Any

# 生成UIとして同じ視覚スロットを占めるパーツ種別。選択ボタンはチャット標準の部品なので含めない。
# Part types that occupy the generated-UI visual slot. Choice buttons are a standard chat part
# and are not among them.
GENERATIVE_UI_PART_TYPES = frozenset({"sandbox_artifact"})
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
    """``text`` の先頭にある回答トレースのブロックを切り離す。

    戻り値は ``(トレースのブロック, 残りの本文)``。先頭がトレースでなければトレースは ``""`` で、本文はそのまま返す。

    Split a leading answer-trace block off ``text``.

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
    """視覚パーツの排他規則を適用し、書かれた順序は保つ。

    生成 UI があれば Web 検索画像は落とす。生成 UI が無いときは、画像パーツを前後のテキストの間に残し、先頭の5枚だけ残す。
    トレースを考慮した配置は、後で :func:`normalize_message_parts_for_display` が行う。

    Enforce visual exclusivity and keep the authored part order.

    A generated UI wins over web-search images. Without a generated UI, inline
    image parts stay between their surrounding text parts, and only the first five
    images are retained. The trace-aware placement is applied later by
    :func:`normalize_message_parts_for_display`.
    """
    normalized = [part for part in (parts or []) if isinstance(part, dict)]
    if any(part.get("type") in GENERATIVE_UI_PART_TYPES for part in normalized):
        return [part for part in normalized if part.get("type") != WEB_SEARCH_IMAGE_PART_TYPE]

    contracted: list[dict[str, Any]] = []
    image_count = 0
    for part in normalized:
        if part.get("type") == WEB_SEARCH_IMAGE_PART_TYPE:
            if image_count >= MAX_WEB_SEARCH_IMAGES_PER_REPLY:
                continue
            image_count += 1
        contracted.append(part)
    return contracted


def normalize_message_parts_for_display(
    parts: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """ペイロードを再検証せずに、表示の規則を適用する。

    :func:`apply_visual_part_contract` に加えて、先頭の回答トレースのブロックを独立したテキストパーツに分け、
    トレースより前に保存された旧形式の画像が「回答までのステップ」の下に出るようにする。
    インライン画像は前後のテキストの間に残る。ペイロードの検証は ``services.generative_ui._decode_message_parts`` の責務。

    Apply the display contract without re-validating payloads.

    On top of :func:`apply_visual_part_contract`, a leading answer-trace block is
    split into its own text part so legacy images saved before the trace render
    below 「回答までのステップ」. Inline images remain between their surrounding
    text parts. Payload validation remains the responsibility of
    ``services.generative_ui._decode_message_parts``.
    """
    contracted = apply_visual_part_contract(parts)
    if not any(part.get("type") == WEB_SEARCH_IMAGE_PART_TYPE for part in contracted):
        return contracted
    first_text_index = next(
        (
            index
            for index, part in enumerate(contracted)
            if part.get("type") == TEXT_PART_TYPE
        ),
        None,
    )
    if first_text_index is None:
        return contracted

    head = contracted[first_text_index]
    trace, remainder = split_answer_trace_block(head.get("text") or "")
    if not trace:
        return contracted

    prefix_parts = contracted[:first_text_index]
    suffix_parts = contracted[first_text_index + 1 :]
    head_parts: list[dict[str, Any]] = [{**head, "text": trace}, *prefix_parts]
    if remainder.strip():
        head_parts.append({**head, "text": remainder})
    return [*head_parts, *suffix_parts]
