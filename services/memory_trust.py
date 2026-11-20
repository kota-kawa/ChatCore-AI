"""記憶（context_facts）の信頼の分け方。本人由来かどうかの定義を 1 か所に置く（ADR 0025）。

本人由来とは、本人が確認した記憶（last_confirmed_at が非 NULL）と、チャットから抽出した記憶（source_kind が chat）。
毎ターン文脈へ入れる `<user_memory>` は本人由来だけで組み（SQL 側の条件）、検索の結果に本人由来でない未確認の記憶
（MCP・取り込みで入って本人が確認していないもの）が含まれたターンは、書き込みツールの「常に承認」を自動実行しない（結果の側の判定）。
SQL の条件と結果の判定は、同じ定数から作る。

Where "originates from the owner" is defined for memory (context_facts), in one place (ADR 0025).

Owner-originated means confirmed by the owner (last_confirmed_at is not NULL) or extracted from chat (source_kind is chat).
The per-turn `<user_memory>` is built from owner-originated memory only (the SQL condition), and a turn whose search result
contains unconfirmed memory that does not originate from the owner (saved through MCP or import and never confirmed) does not run
writes on its own under "always approve" (the result-side check). Both are built from the same constant.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, or_

# 抽出が本人の発話そのものの引用をコードで照合して通ったものだけを保存するため、本人由来として扱う出所。
# The source kind treated as the owner's: extraction saves only what passed a code check against a verbatim quote of the owner's words.
OWNER_EXTRACTED_SOURCE_KIND = "chat"


def is_owner_originated(*, confirmed: bool, source_kind: Any) -> bool:
    """確認済み、またはチャットから抽出した記憶なら True。

    True for a memory the owner confirmed or one extracted from chat.
    """
    return confirmed or source_kind == OWNER_EXTRACTED_SOURCE_KIND


def owner_originated_condition(last_confirmed_at: ColumnElement[Any], source_kind: ColumnElement[Any]) -> ColumnElement[bool]:
    """`is_owner_originated` と同じ定義の SQL 条件。

    The SQL condition with the same definition as `is_owner_originated`.
    """
    return or_(last_confirmed_at.is_not(None), source_kind == OWNER_EXTRACTED_SOURCE_KIND)


def contains_non_owner_unconfirmed_memory(memories: Any) -> bool:
    """検索結果の記憶の一覧に、本人由来でない未確認の記憶（確認済みでなく、チャット由来でもない）が 1 件でもあれば True。

    形の合わない要素は、本人由来と確かめられないので未確認として数える。

    True when a result's memory list has at least one unconfirmed memory that does not originate from the owner. An item of the wrong shape
    cannot be shown to be the owner's, so it counts as unconfirmed.
    """
    if not isinstance(memories, Sequence) or isinstance(memories, (str, bytes)):
        return False
    return any(
        not isinstance(memory, dict)
        or not is_owner_originated(confirmed=memory.get("confirmed") is True, source_kind=memory.get("source_kind"))
        for memory in memories
    )
