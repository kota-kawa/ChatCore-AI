"""Detect private text leaking into a public post proposal.

チャットの生成中に読んだ非公開の内容（メモ本文・抜粋、llm_profile_context、自分の Task・
個人Skill の本文）が公開投稿の新規作成提案に 50 字以上そのまま一致したら、警告
（private_text_in_public_post）を出す。ブロックはしない: 利用者が確認チェックを入れれば
承認できる（services/chat_tool_approval_service.py と ToolApprovalDecisionRequest を参照）。

Warns, but never blocks, when private content read during the turn (memo bodies/excerpts,
llm_profile_context, the user's own Task and personal Skill bodies) reappears verbatim, 50
characters or more, inside a new public post proposal. The user can still approve after
acknowledging the warning (see services/chat_tool_approval_service.py and
ToolApprovalDecisionRequest).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

# 非公開の読み取り結果からテキストを拾うキー。メモ（content・excerpt）、自分用プロンプト
# （prompt_content 他）、個人Skill（instructions）に共通で使う。
# Keys used to pull text out of a private read result: memo (content, excerpt), the user's own
# prompts (prompt_content and friends), and personal Skills (instructions).
PRIVATE_TEXT_KEYS = frozenset(
    {
        "content",
        "excerpt",
        "instructions",
        "prompt_content",
        "response_rules",
        "output_skeleton",
        "input_examples",
        "output_examples",
    }
)

# 一致の下限。これ未満は偶然の一致（定型句など）として無視する。
# Minimum match length; anything shorter is ignored as a coincidental (boilerplate) overlap.
MIN_OVERLAP_LENGTH = 50
# 1件の非公開テキストが長すぎると比較コストが跳ね上がるため、末尾を切り捨てて比較する。
# 提案文の側は公開プロンプトの上限で既に抑えられている。
# A single private text is capped before comparison so the cost stays bounded; the candidate
# side is already bounded by the shared-prompt field limits.
MAX_PRIVATE_TEXT_CHARS = 20_000
# 追跡する非公開テキストの件数の上限（直近優先）。
# Cap on how many private texts are tracked (most recent first).
MAX_TRACKED_TEXTS = 20
# カードに出す一致箇所の最大件数と、1件あたりの表示上限文字数。
# Maximum number of matches shown on the card, and the display length cap for each.
MAX_REPORTED_MATCHES = 3
MAX_EXCERPT_DISPLAY_CHARS = 200


class PrivateTextTracker:
    """Accumulates private text read during one turn for public-post overlap checks."""

    def __init__(self, *, seed: str = "") -> None:
        self._texts: list[str] = []
        self._chunk_tails: OrderedDict[str, tuple[int, str]] = OrderedDict()
        seed_text = seed.strip()
        if seed_text:
            self.add(seed_text)

    def add(self, text: str) -> None:
        normalized = (text or "").strip()
        if not normalized:
            return
        self._texts.append(normalized[:MAX_PRIVATE_TEXT_CHARS])
        if len(self._texts) > MAX_TRACKED_TEXTS:
            self._texts = self._texts[-MAX_TRACKED_TEXTS:]

    def add_chunk(self, group_key: str, start: int, text: str) -> None:
        """Track one private read chunk and the seam with its adjacent predecessor."""
        if not text or not text.strip():
            return
        chunk = text[:MAX_PRIVATE_TEXT_CHARS]
        previous = self._chunk_tails.get(group_key)
        tail_source = chunk
        if previous is not None:
            previous_end, previous_tail = previous
            if previous_end == start:
                tail_source = previous_tail + chunk
                self.add(tail_source)
            else:
                self.add(chunk)
        else:
            self.add(chunk)

        end = start + len(chunk)
        self._chunk_tails[group_key] = (end, tail_source[-(MIN_OVERLAP_LENGTH - 1) :])
        self._chunk_tails.move_to_end(group_key)
        while len(self._chunk_tails) > MAX_TRACKED_TEXTS:
            self._chunk_tails.popitem(last=False)

    def find_overlaps(self, candidate: str) -> list[str]:
        """Return up to MAX_REPORTED_MATCHES excerpts of candidate that reappear from private text."""
        candidate_text = (candidate or "").strip()
        if len(candidate_text) < MIN_OVERLAP_LENGTH or not self._texts:
            return []
        matches: list[str] = []
        seen: set[str] = set()
        for private_text in self._texts:
            if len(private_text) < MIN_OVERLAP_LENGTH:
                continue
            windows: dict[str, int] = {}
            for private_index in range(len(private_text) - MIN_OVERLAP_LENGTH + 1):
                windows.setdefault(private_text[private_index : private_index + MIN_OVERLAP_LENGTH], private_index)
            index = 0
            while index <= len(candidate_text) - MIN_OVERLAP_LENGTH:
                private_index = windows.get(candidate_text[index : index + MIN_OVERLAP_LENGTH])
                if private_index is None:
                    index += 1
                    continue
                end = index + MIN_OVERLAP_LENGTH
                private_end = private_index + MIN_OVERLAP_LENGTH
                while (
                    end < len(candidate_text)
                    and private_end < len(private_text)
                    and candidate_text[end] == private_text[private_end]
                ):
                    end += 1
                    private_end += 1
                excerpt = candidate_text[index:end]
                index = end
                key = excerpt[:MAX_EXCERPT_DISPLAY_CHARS]
                if key in seen:
                    continue
                seen.add(key)
                matches.append(key if len(excerpt) <= MAX_EXCERPT_DISPLAY_CHARS else f"{key}…")
                if len(matches) >= MAX_REPORTED_MATCHES:
                    return matches
        return matches


# 読み取り結果（JSON になれる入れ子の dict/list）から、既知のキーの文字列だけを拾う。
# Pull only the strings under known keys out of a read result (a JSON-able nested dict/list).
def extract_private_texts(payload: Any) -> list[str]:
    found: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in PRIVATE_TEXT_KEYS and isinstance(value, str):
                    found.append(value)
                elif isinstance(value, (dict, list)):
                    _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return found
