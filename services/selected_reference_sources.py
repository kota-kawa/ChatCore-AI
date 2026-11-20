"""チャット 1 ターンで選ばれたメモ・共有プロンプトの参照元を、使ってよい検索関数へ組み立てる。

送信・再生成・編集再生成の 3 経路が同じ規則（リクエストで有効化され、かつセッションが読める参照元だけをモデルへ渡す）を
共有するため、この規則をここに 1 か所だけ置いている。

Wiring for the memo / shared-prompt reference sources a chat turn has selected.

Chat posts, regenerations and edit-regenerations all need the same rule: a reference source
reaches the model only when the request enabled it and the session is allowed to read it.
Keeping that rule in one place means the three routes cannot drift apart.
"""

from __future__ import annotations

import inspect
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from services.personal_knowledge import build_personal_overview
from services.selected_reference_context import PERSONAL_KNOWLEDGE_SOURCE, lookup_query_key

logger = logging.getLogger(__name__)

__all__ = [
    "DeduplicatedLookup",
    "SelectedReferenceSearchers",
    "build_memory_searcher",
    "build_selected_reference_searchers",
]


class DeduplicatedLookup:
    """同じクエリは 1 ターンに 1 回しか実行しない検索ラッパー。

    選ばれた参照元は生成前に先読みされ、その後も絞り込み検索のためにツールとして使える。このラッパーが無いと、
    先読み済みと同じクエリでツールを呼んだ場合に、同じメモ本文が二重に文脈へ入ってしまう。

    Run each distinct query at most once per turn.

    The selected sources are prefetched before generation and their tools stay available for
    narrower follow-up searches. Without this wrapper a model that calls a tool with the query
    already prefetched would push the very same memo bodies into the context a second time.
    """

    def __init__(self, search: Callable[[str], Any], *, source_label: str) -> None:
        self._search = search
        self._source_label = source_label
        self._lock = threading.Lock()
        self._searched: set[str] = set()

    # 実行済みのクエリなら検索せず already_searched を返し、未実行なら検索して成功時だけ記録する。
    # 空クエリ（key が空）は重複判定の対象にせず、毎回そのまま検索へ渡す。
    # 検索が非同期（DB 検索）のときは、結果が出てから記録する awaitable を返す。呼び出し側は同期の値と awaitable の両方を受け取る。
    # Return already_searched for a query run earlier; otherwise search and record it only on success.
    # An empty query (empty key) is never deduplicated and always goes straight to the search.
    # With an async search (a database lookup) an awaitable is returned that records the query once the result is in; callers accept
    # both a plain value and an awaitable.
    def __call__(self, query: str) -> Any:
        key = lookup_query_key(query)
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
        if inspect.isawaitable(payload):
            return self._record_when_done(key, payload)
        self._record(key, payload)
        return payload

    async def _record_when_done(self, key: str, pending: Awaitable[Any]) -> Any:
        payload = await pending
        self._record(key, payload)
        return payload

    # 失敗したクエリは記録しない。記録すると、一過性の障害からの引き直しが
    # 「検索済み」として空振りしてしまう。
    # A failed query is not recorded: recording it would turn the retry that recovers from a
    # transient outage into an "already searched" no-op.
    def _record(self, key: str, payload: Any) -> None:
        if key and isinstance(payload, dict) and payload.get("status") != "failed":
            with self._lock:
                self._searched.add(key)


@dataclass(frozen=True)
class SelectedReferenceSearchers:
    """1 回のチャットターンが使える検索関数と、有効化されたが使えなかった参照元をまとめる。

    The lookups a single chat turn may use, plus the enabled ones it could not use.
    """

    personal_knowledge: Callable[[str], dict[str, Any]] | None = None
    shared_prompt: Callable[[str], dict[str, Any]] | None = None
    # 検索が空振りしたときに使う、クエリ非依存の棚卸し。
    # Query-independent inventory used when a search comes back empty.
    personal_overview: Callable[[], dict[str, Any]] | None = None
    unavailable_sources: tuple[str, ...] = ()


# リクエストのフラグとログイン状態から、このターンで実際に実行してよい検索関数を組み立てる。
# 検索関数は呼び出し側から注入されるので、実際の DB や検索を使わずにテストできる。
# Build the lookups this turn may run from the request flags and the sign-in state.
# The search functions are injected by the caller, so the rule is testable without a real database or search.
def build_selected_reference_searchers(
    *,
    user_id: int | None,
    use_personal_knowledge: bool,
    use_shared_prompts: bool,
    search_personal_knowledge: Callable[..., dict[str, Any]],
    search_shared_prompts: Callable[..., dict[str, Any]],
    personal_overview: Callable[..., dict[str, Any]] = build_personal_overview,
) -> SelectedReferenceSearchers:
    """リクエストのフラグを、このターンで実際に実行してよい検索関数へ解決する。

    Resolve the request flags into the lookups this turn is actually allowed to run.
    """
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
                source_label="memo",
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


# モデルが呼ぶ記憶の検索ツール用の検索関数。「＋→メモ」のトグルとは無関係で、記憶を読んでよいターン（services/user_memory.py の
# should_use_user_memory）だけ渡す。事前の検索はしない。同じ検索語の繰り返しは、メモや共有プロンプトと同じ DeduplicatedLookup で止める。
# The lookup behind the model-called memory_search tool. It is independent of the "+ -> Memo" toggle and handed over only on a turn that
# may read memory (should_use_user_memory in services/user_memory.py). Nothing is prefetched. A repeated query is stopped by the same
# DeduplicatedLookup the memo and shared-prompt tools use.
def build_memory_searcher(
    *,
    user_id: int | None,
    memory_enabled: bool,
    search_memory: Callable[..., Any],
) -> DeduplicatedLookup | None:
    if user_id is None or not memory_enabled:
        return None
    return DeduplicatedLookup(partial(search_memory, user_id), source_label="memory")
