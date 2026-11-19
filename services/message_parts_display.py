# アシスタントメッセージのパーツ（実行記録／テキスト／生成UI／選択ボタン／Web検索画像）の表示順を決める。
# 実行記録（「回答までのステップ」）は常に先頭に 1 つだけ置く。
# sandbox ArtifactとWeb検索画像は1ターン内で排他。宣言的UIは画像と共存する。
# 選択ボタンは生成UIではないため、この排他に加わらず、どちらとも同じ返信に並ぶ。
# 実行記録を本文の先頭へ HTML で前置していた頃の回答は、読み出し時にここで本文と記録へ分ける。
# Owns the display ordering contract for assistant message parts (execution record / text /
# generated UI / choice buttons / web-search images). The execution record (the "steps to the
# answer") always comes first, and there is at most one. Sandbox Artifacts and web-search
# images are mutually exclusive; native UI coexists with images. Choice buttons are not generated UI,
# so they take no part in that exclusivity and can sit beside either. Answers saved while the record
# was still prepended to the body as HTML are split into body and record here when they are read.

from __future__ import annotations

import re
from typing import Any

from services.answer_trace import is_answer_trace_part, legacy_answer_trace_part

# 生成UIの存在判定と、画像との排他を担当するArtifactの集合を区別する。
# Keep Artifact image exclusivity separate from the set of all generated UI part types.
ARTIFACT_PART_TYPES = frozenset({"sandbox_artifact"})
GENERATIVE_UI_PART_TYPES = frozenset({"sandbox_artifact", "structured_ui"})
WEB_SEARCH_IMAGE_PART_TYPE = "web_search_image"
TEXT_PART_TYPE = "text"
MAX_WEB_SEARCH_IMAGES_PER_REPLY = 5

# 構造化する前の実行記録は、このクラスを持つ <details> として本文の先頭に保存されている。
# 新しい回答はこの HTML を作らない。保存済みの回答を読むときの切り分けにだけ使う。
# Before it was structured, the execution record was saved at the head of the body as a <details>
# with this class. New answers never produce this markup; it is only used to split saved answers.
_LEGACY_TRACE_BLOCK_START = '<details class="web-search-sources web-search-sources--trace"'
# トレース内部にもステップ用の <details> が入れ子になるため、開閉を数えて末尾を探す。
# Steps nest their own <details>, so the block end is found by counting tags.
_DETAILS_TAG_RE = re.compile(r"<details\b|</details\s*>", re.IGNORECASE)


def _split_legacy_answer_trace_block(text: str) -> tuple[str, str]:
    """``text`` の先頭にある、構造化前の実行記録の HTML ブロックを切り離す。

    戻り値は ``(ブロック, 残りの本文)``。先頭がそのブロックでなければブロックは ``""`` で、本文はそのまま返す。

    Split the pre-structuring execution-record markup off the head of ``text``.

    Returns ``(block, remaining_text)``. When the text does not start with such a block, the
    block is ``""`` and the text is returned unchanged.
    """
    if not isinstance(text, str) or not text:
        return "", text if isinstance(text, str) else ""
    stripped = text.lstrip()
    if not stripped.startswith(_LEGACY_TRACE_BLOCK_START):
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


# Web検索の表示ブロック（「回答までのステップ」と旧形式の参照サイト一覧）は
# <details class="web-search-sources …">…</details> として本文へ差し込まれる。
# Web-search display blocks (the answer trace and the legacy source list) are injected
# into the body as <details class="web-search-sources …">…</details>.
_WEB_SEARCH_SOURCES_BLOCK_RE = re.compile(
    r"<details\b[^>]*\bclass\s*=\s*(?P<quote>[\"'])[^\"']*web-search-sources[^\"']*(?P=quote)[^>]*>"
    r"(?:(?!</?details\b)[\s\S])*?</details>",
    re.IGNORECASE,
)


def strip_web_search_sources_html(text: str) -> str:
    """本文から Web 検索の表示ブロックを、入れ子も含めてすべて取り除く。

    表示専用のHTMLなので、本文だけを見たい処理（意図の判定、代替UIの生成、モデルへ戻す履歴）では先に除く。

    Remove every web-search display block, nested ones included.

    The blocks are display-only markup, so callers that need the prose alone (intent
    inference, fallback UI generation, history replayed to the model) strip them first.
    """
    if "web-search-sources" not in text:
        return text
    # 正規表現だけではネスト全体を一度に消せないため、内側から消して安定するまで繰り返す。
    # A regular expression cannot remove a whole nest at once, so the innermost blocks go
    # first and the pass repeats until nothing changes.
    current = text
    while True:
        stripped = _WEB_SEARCH_SOURCES_BLOCK_RE.sub("", current)
        if stripped == current:
            return current
        current = stripped


def read_legacy_answer_trace_part(part: dict[str, Any]) -> dict[str, Any] | None:
    """保存済みのパーツから、構造化前の実行記録のパーツを読む。

    HTML が構造化前の記録のブロックそのものである場合だけ受け入れる。それ以外の HTML を、記録として
    本文の外に描かせない。

    Read a pre-structuring execution-record part back from stored parts.

    The markup is accepted only when it is exactly one such record block, so no other HTML can be
    rendered outside the body in the record's place.
    """
    html = part.get("html")
    block, remainder = _split_legacy_answer_trace_block(html if isinstance(html, str) else "")
    if not block or remainder.strip():
        return None
    return legacy_answer_trace_part(block)


def apply_visual_part_contract(parts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """視覚パーツの排他規則を適用し、書かれた順序は保つ。

    Sandbox Artifact があれば Web 検索画像は落とす。宣言的 UI は画像と共存する。
    Artifact が無いときは画像を前後のテキストの間に残し、先頭の5枚だけ残す。
    実行記録を先頭へ置く処理は、後で :func:`normalize_message_parts_for_display` が行う。

    Enforce visual exclusivity and keep the authored part order.

    A sandbox Artifact wins over web-search images; native UI coexists with them. Without a generated UI, inline
    image parts stay between their surrounding text parts, and only the first five
    images are retained. Moving the execution record to the front is applied later by
    :func:`normalize_message_parts_for_display`.
    """
    normalized = [part for part in (parts or []) if isinstance(part, dict)]
    if any(part.get("type") in ARTIFACT_PART_TYPES for part in normalized):
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

    :func:`apply_visual_part_contract` に加えて、実行記録を先頭に 1 つだけ置く。インライン画像は前後のテキストの
    間に残る。ペイロードの検証は ``services.generative_ui._decode_message_parts`` の責務。

    Apply the display contract without re-validating payloads.

    On top of :func:`apply_visual_part_contract`, the execution record is placed first and kept
    single. Inline images remain between their surrounding text parts. Payload validation remains
    the responsibility of ``services.generative_ui._decode_message_parts``.
    """
    contracted = apply_visual_part_contract(parts)
    trace = next((part for part in contracted if is_answer_trace_part(part)), None)
    if trace is None:
        return contracted
    return [trace, *(part for part in contracted if not is_answer_trace_part(part))]


def separate_legacy_answer_trace(
    message: str,
    parts: list[dict[str, Any]] | None,
) -> tuple[str, list[dict[str, Any]] | None]:
    """構造化前に保存された回答を、本文と実行記録のパーツへ分ける。旧形式でなければそのまま返す。

    旧形式では、実行記録の HTML が本文と最初のテキストパーツの先頭に入っている。保存済みの回答を読み出す境界で
    ここを通し、以降の処理（表示、モデルへ戻す履歴、コピー）が本文だけを扱えるようにする。保存済みの行は
    書き換えない。記録より前に保存されていた画像は、記録の後ろに並ぶ。

    Split an answer saved before structuring into its body and an execution-record part; anything
    else is returned unchanged.

    Such an answer carries the record's markup at the head of both the body and the first text part.
    Saved answers pass through here at the read boundary so that everything after it (display, history
    replayed to the model, copying) deals with the body alone. Stored rows are never rewritten. Images
    saved ahead of the record end up after it.
    """
    trace_html, body = _split_legacy_answer_trace_block(message)
    legacy_part = legacy_answer_trace_part(trace_html)
    if legacy_part is None:
        return message, parts

    remaining: list[dict[str, Any]] = []
    for part in parts or []:
        if is_answer_trace_part(part):
            continue
        if part.get("type") == TEXT_PART_TYPE:
            part_trace, part_text = _split_legacy_answer_trace_block(part.get("text") or "")
            if part_trace:
                if not part_text.strip():
                    continue
                part = {**part, "text": part_text}
        remaining.append(part)
    if not parts and body.strip():
        remaining = [{"type": TEXT_PART_TYPE, "text": body}]
    return body, [legacy_part, *remaining]
