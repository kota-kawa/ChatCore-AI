"""Detect private text leaking into a public post proposal.

チャットの生成中に読んだ非公開の内容（メモ本文・抜粋、llm_profile_context、自分の Task・
個人Skill の本文）が公開投稿（publish_prompt）の提案に 50 字以上そのまま一致したら、警告
（private_text_in_public_post）を出す。ブロックはしない: 利用者が確認チェックを入れれば
承認できる（services/chat_tool_approval_service.py と ToolApprovalDecisionRequest を参照）。

Warns, but never blocks, when private content read during the turn (memo bodies/excerpts,
llm_profile_context, the user's own Task and personal Skill bodies) reappears verbatim, 50
characters or more, inside a publish_prompt proposal. The user can still approve after
acknowledging the warning (see services/chat_tool_approval_service.py and
ToolApprovalDecisionRequest).
"""

from __future__ import annotations

from difflib import SequenceMatcher
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
    """Accumulates private text read during one turn, for the publish_prompt overlap check."""

    def __init__(self, *, seed: str = "") -> None:
        self._texts: list[str] = []
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

    def find_overlaps(self, candidate: str) -> list[str]:
        """Return up to MAX_REPORTED_MATCHES excerpts of candidate that reappear from private text."""
        candidate_text = (candidate or "").strip()
        if not candidate_text or not self._texts:
            return []
        matches: list[str] = []
        seen: set[str] = set()
        for private_text in self._texts:
            matcher = SequenceMatcher(None, private_text, candidate_text, autojunk=False)
            for block in matcher.get_matching_blocks():
                if block.size < MIN_OVERLAP_LENGTH:
                    continue
                excerpt = candidate_text[block.b : block.b + block.size]
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
