# 回答に付く実行記録（「回答までのステップ」）の契約を持つ。
# 実行記録は本文に混ぜず、回答パーツの 1 つとして構造化データのまま保存・配信する。ここが持つのは
# パーツの種類、データの形と上限、保存・読み出し時の検証だけで、ステップの作り方は
# web_search_trace.py、表示順は message_parts_display.py が担当する。
# Owns the contract of the execution record attached to an answer (the "steps to the answer").
# The record is never mixed into the prose: it is stored and delivered as structured data in its own
# answer part. This module holds the part types, the shape and limits of the data, and the validation
# applied when it is stored or read back. Building the steps belongs to web_search_trace.py and the
# display order to message_parts_display.py.

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ANSWER_TRACE_PART_TYPE = "answer_trace"
# 構造化する前に保存された回答の、本文先頭にあった表示用 HTML。読み出し時に本文から切り離してこの種類で渡す。
# 読み出した回答を別のルームへ複製するときは、このパーツのまま保存する。
# The display markup that led the body of answers saved before the record was structured. It is split
# off the body when such an answer is read and handed over under this type. An answer read this way
# and copied into another room is stored with this part as is.
LEGACY_ANSWER_TRACE_PART_TYPE = "legacy_answer_trace"
ANSWER_TRACE_VERSION = 1

# ステップの種類。画面はこの値でアイコンと色を選ぶ。
# Step kinds; the screen picks an icon and a colour from this value.
ANSWER_TRACE_STEP_KINDS = frozenset(
    {
        "decide",
        "search",
        "reuse",
        "read",
        "follow",
        "review",
        "answer",
        "warning",
        "knowledge",
        "prompt",
        "info",
    }
)
DEFAULT_ANSWER_TRACE_STEP_KIND = "info"

# ステップの状態。running は実行中、failed は結果を回答に使えなかったことを表す。
# Step statuses: running is still in progress, failed means the result could not be used.
ANSWER_TRACE_STEP_STATUSES = frozenset({"running", "done", "failed"})
DEFAULT_ANSWER_TRACE_STEP_STATUS = "done"

MAX_ANSWER_TRACE_STEPS = 60
MAX_ANSWER_TRACE_STEP_SOURCES = 40
MAX_ANSWER_TRACE_STEP_CHIPS = 8
STEP_TITLE_MAX_CHARS = 120
STEP_DETAIL_MAX_CHARS = 260
STEP_QUERY_MAX_CHARS = 120
STEP_BADGE_MAX_CHARS = 24
STEP_CHIP_MAX_CHARS = 40
SUMMARY_MAX_CHARS = 200
SOURCE_TITLE_MAX_CHARS = 300
SOURCE_HOSTNAME_MAX_CHARS = 255
SOURCE_URL_MAX_CHARS = 2048
MAX_SOURCE_LINK_DEPTH = 9

_STEP_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")


def _text(value: Any, max_chars: int) -> str:
    # 空白を 1 つにまとめ、上限を超えた分は末尾を「...」に置き換える。
    # Collapse whitespace and replace anything past the limit with a trailing "...".
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def is_safe_http_url(url: Any) -> bool:
    """リンクや画像の参照先として画面へ出せる HTTP(S) の URL かを返す。

    Return whether the URL is an HTTP(S) URL that may be exposed as a link or image target.
    """
    if not isinstance(url, str) or not url or len(url) > SOURCE_URL_MAX_CHARS:
        return False
    if any(char in url for char in ("\r", "\n", "\x00")):
        return False
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return False
    return bool(
        parsed.scheme.lower() in {"http", "https"}
        and parsed.netloc
        and parsed.username is None
        and parsed.password is None
    )


def site_favicon_url(url: str) -> str:
    """サイト直下の favicon の URL を返す。出典が固有の favicon を持たないときの既定値。

    Return the favicon URL at the site root, the default when a source carries none of its own.
    """
    parsed = urlsplit(url.strip())
    return urlunsplit((parsed.scheme, parsed.netloc, "/favicon.ico", "", ""))


def _normalize_source(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    url = raw.get("url").strip() if isinstance(raw.get("url"), str) else ""
    if not is_safe_http_url(url):
        return None
    hostname = _text(raw.get("hostname"), SOURCE_HOSTNAME_MAX_CHARS)
    title = _text(raw.get("title"), SOURCE_TITLE_MAX_CHARS) or url
    favicon_url = raw.get("favicon_url").strip() if isinstance(raw.get("favicon_url"), str) else ""
    if not is_safe_http_url(favicon_url):
        favicon_url = site_favicon_url(url)
    fallback_label = _text(raw.get("fallback_label"), 8)[:1] or (
        (hostname or title).removeprefix("www.")[:1].upper() or "?"
    )
    link_depth = raw.get("link_depth")
    if not isinstance(link_depth, int) or isinstance(link_depth, bool):
        link_depth = 0
    return {
        "url": url,
        "title": title,
        "hostname": hostname,
        "favicon_url": favicon_url,
        "fallback_label": fallback_label,
        "link_depth": max(0, min(link_depth, MAX_SOURCE_LINK_DEPTH)),
        "linked_from": _text(raw.get("linked_from"), SOURCE_HOSTNAME_MAX_CHARS),
    }


def _normalize_step(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = _text(raw.get("title"), STEP_TITLE_MAX_CHARS)
    if not title:
        return None
    kind = raw.get("kind")
    status = raw.get("status")
    raw_chips = raw.get("chips") if isinstance(raw.get("chips"), (list, tuple)) else ()
    raw_sources = raw.get("sources") if isinstance(raw.get("sources"), (list, tuple)) else ()
    chips = [chip for chip in (_text(chip, STEP_CHIP_MAX_CHARS) for chip in raw_chips) if chip]
    sources = [source for source in (_normalize_source(item) for item in raw_sources) if source]
    return {
        "id": raw.get("id") if isinstance(raw.get("id"), str) else "",
        "kind": kind if kind in ANSWER_TRACE_STEP_KINDS else DEFAULT_ANSWER_TRACE_STEP_KIND,
        "status": status if status in ANSWER_TRACE_STEP_STATUSES else DEFAULT_ANSWER_TRACE_STEP_STATUS,
        "title": title,
        "detail": _text(raw.get("detail"), STEP_DETAIL_MAX_CHARS),
        "query": _text(raw.get("query"), STEP_QUERY_MAX_CHARS),
        "badge": _text(raw.get("badge"), STEP_BADGE_MAX_CHARS),
        "chips": chips[:MAX_ANSWER_TRACE_STEP_CHIPS],
        "sources": sources[:MAX_ANSWER_TRACE_STEP_SOURCES],
    }


def normalize_answer_trace(raw: Any) -> dict[str, Any] | None:
    """実行記録を契約どおりの形へ正規化する。ステップが 1 つも残らなければ ``None``。

    保存する前と読み出した後の両方で通す。上限を超えた分は切り詰め、形の合わない要素は捨てる。
    ステップの ID は回答の中で一意にし、欠けている・重複している場合は並び順から振り直す。

    Normalize an execution record to the contract; ``None`` when no step survives.

    Applied both before storing and after reading. Anything over a limit is truncated and malformed
    items are dropped. Step ids are unique within the answer; a missing or duplicate id is reassigned
    from the step's position.
    """
    if not isinstance(raw, dict) or raw.get("version") != ANSWER_TRACE_VERSION:
        return None
    raw_steps = raw.get("steps") if isinstance(raw.get("steps"), (list, tuple)) else ()
    steps = [step for step in (_normalize_step(item) for item in raw_steps[:MAX_ANSWER_TRACE_STEPS]) if step]
    # 使える ID は最初に現れたステップのものとして先に確保する。振り直した ID が、後ろのステップが元から
    # 持っている ID とぶつからないようにするため。
    # Usable ids are reserved for the first step that carries them before anything is reassigned, so a
    # reassigned id can never collide with one a later step already has.
    reserved_ids: set[str] = set()
    keeps_id: list[bool] = []
    for step in steps:
        usable = bool(_STEP_ID_RE.fullmatch(step["id"])) and step["id"] not in reserved_ids
        keeps_id.append(usable)
        if usable:
            reserved_ids.add(step["id"])
    next_number = 1
    for step, keeps in zip(steps, keeps_id, strict=True):
        if keeps:
            continue
        while f"s{next_number}" in reserved_ids:
            next_number += 1
        step["id"] = f"s{next_number}"
        reserved_ids.add(step["id"])
    if not steps:
        return None
    return {
        "version": ANSWER_TRACE_VERSION,
        "summary": _text(raw.get("summary"), SUMMARY_MAX_CHARS),
        "steps": steps,
    }


def answer_trace_part(trace: Any) -> dict[str, Any] | None:
    """実行記録を回答パーツにする。記録として成り立たなければ ``None``。

    Wrap an execution record as an answer part; ``None`` when it is not a valid record.
    """
    normalized = normalize_answer_trace(trace)
    if normalized is None:
        return None
    return {"type": ANSWER_TRACE_PART_TYPE, "trace": normalized}


def with_answer_trace_part(
    message_parts: list[dict[str, Any]] | None,
    text: str,
    trace: Any,
) -> list[dict[str, Any]] | None:
    """実行記録を回答パーツの先頭へ足す。記録が無ければ元のパーツをそのまま返す。

    パーツを持たない本文だけの回答では、本文をテキストパーツにして記録の後ろへ置く。

    Put the execution record at the head of the answer parts; without one the parts are returned as is.

    For a body-only answer that has no parts, the body becomes a text part placed after the record.
    """
    part = answer_trace_part(trace)
    if part is None:
        return message_parts
    base_parts = message_parts if message_parts else ([{"type": "text", "text": text}] if text.strip() else [])
    return [part, *(existing for existing in base_parts if not is_answer_trace_part(existing))]


def legacy_answer_trace_part(html: Any) -> dict[str, Any] | None:
    """構造化前の表示用 HTML を、本文とは別のパーツにする。空なら ``None``。

    Wrap pre-structuring display markup as a part of its own; ``None`` when empty.
    """
    if not isinstance(html, str) or not html.strip():
        return None
    return {"type": LEGACY_ANSWER_TRACE_PART_TYPE, "html": html}


def is_answer_trace_part(part: Any) -> bool:
    """実行記録のパーツ（構造化・旧形式のどちらか）かを返す。

    Return whether the part is an execution record, structured or legacy.
    """
    return isinstance(part, dict) and part.get("type") in (
        ANSWER_TRACE_PART_TYPE,
        LEGACY_ANSWER_TRACE_PART_TYPE,
    )
