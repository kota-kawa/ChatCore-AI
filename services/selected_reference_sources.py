"""Wiring for the memo / shared-prompt reference sources a chat turn has selected.

Chat posts, regenerations and edit-regenerations all need the same rule: a reference source
reaches the model only when the request enabled it and the session is allowed to read it.
Keeping that rule in one place means the three routes cannot drift apart.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from services.personal_knowledge import build_personal_overview
from services.selected_reference_context import PERSONAL_KNOWLEDGE_SOURCE

logger = logging.getLogger(__name__)

__all__ = [
    "DeduplicatedLookup",
    "SelectedReferenceSearchers",
    "build_selected_reference_searchers",
]


class DeduplicatedLookup:
    """Run each distinct query at most once per turn.

    The selected sources are prefetched before generation and their tools stay available for
    narrower follow-up searches. Without this wrapper a model that calls a tool with the query
    already prefetched would push the very same memo bodies into the context a second time.
    """

    def __init__(self, search: Callable[[str], dict[str, Any]], *, source_label: str) -> None:
        self._search = search
        self._source_label = source_label
        self._lock = threading.Lock()
        self._searched: set[str] = set()

    @staticmethod
    def _key(query: str) -> str:
        return " ".join(str(query or "").split()).casefold()

    def __call__(self, query: str) -> dict[str, Any]:
        key = self._key(query)
        if key:
            with self._lock:
                if key in self._searched:
                    logger.info(
                        "Skipping a repeated selected %s lookup for an already searched query.",
                        self._source_label,
                    )
                    return {
                        "status": "already_searched",
                        "query": query,
                        "message": (
                            "This exact query was already searched for this turn and its results "
                            "are already in the conversation. Do not repeat it: search with "
                            "materially different keywords, or answer from what you already have."
                        ),
                    }

        payload = self._search(query)
        # 失敗したクエリは記録しない。記録すると、一過性の障害からの引き直しが
        # 「検索済み」として空振りしてしまう。
        # A failed query is not recorded: recording it would turn the retry that recovers from a
        # transient outage into an "already searched" no-op.
        if key and isinstance(payload, dict) and payload.get("status") != "failed":
            with self._lock:
                self._searched.add(key)
        return payload


@dataclass(frozen=True)
class SelectedReferenceSearchers:
    """The lookups a single chat turn may use, plus the enabled ones it could not use."""

    personal_knowledge: Callable[[str], dict[str, Any]] | None = None
    shared_prompt: Callable[[str], dict[str, Any]] | None = None
    # 検索が空振りしたときに使う、クエリ非依存の棚卸し。
    # Query-independent inventory used when a search comes back empty.
    personal_overview: Callable[[], dict[str, Any]] | None = None
    unavailable_sources: tuple[str, ...] = ()


def build_selected_reference_searchers(
    *,
    user_id: int | None,
    use_personal_knowledge: bool,
    use_shared_prompts: bool,
    search_personal_knowledge: Callable[..., dict[str, Any]],
    search_shared_prompts: Callable[..., dict[str, Any]],
    personal_overview: Callable[..., dict[str, Any]] = build_personal_overview,
) -> SelectedReferenceSearchers:
    """Resolve the request flags into the lookups this turn is actually allowed to run."""
    personal_knowledge: Callable[[str], dict[str, Any]] | None = None
    overview: Callable[[], dict[str, Any]] | None = None
    unavailable: list[str] = []
    if use_personal_knowledge:
        if user_id is None:
            # メモは本人のデータなので未ログインでは読めない。黙って落とすと、期限切れタブからの
            # 送信が根拠なしの回答へ静かに変わるため、使えなかったことを呼び出し側へ持ち回る。
            # Memos are owner-only data and unreadable while signed out. Dropping that silently
            # would turn a post from an expired tab into an ungrounded answer with no explanation,
            # so the unusable source is carried back to the caller instead.
            logger.info("Memo lookup was requested without a signed-in session; skipping it.")
            unavailable.append(PERSONAL_KNOWLEDGE_SOURCE)
        else:
            personal_knowledge = DeduplicatedLookup(
                partial(search_personal_knowledge, user_id),
                source_label="memo and My Context",
            )
            overview = partial(personal_overview, user_id)

    shared_prompt: Callable[[str], dict[str, Any]] | None = None
    if use_shared_prompts:
        # 共有プロンプトは公開データなので、未ログインでも参照できる。
        # Shared prompts are public, so signed-out visitors may read them too.
        shared_prompt = DeduplicatedLookup(search_shared_prompts, source_label="shared prompt")

    return SelectedReferenceSearchers(
        personal_knowledge=personal_knowledge,
        shared_prompt=shared_prompt,
        personal_overview=overview,
        unavailable_sources=tuple(unavailable),
    )
