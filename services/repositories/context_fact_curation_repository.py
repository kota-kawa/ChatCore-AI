"""記憶の画面からの利用者の操作のうち、複数の行にまたがる書き込み(置き換えを元に戻す)を永続化する。利用者単位の advisory lock を取ってから
状態を確かめ直し、同じトランザクションの中で行う。トランザクションは呼び出し側が持つ。services/context_vault_service.py から使われる。

Owner-scoped write of the memory screen that spans several rows: undoing a replacement. It takes the per-user advisory lock, re-checks the
state and writes inside one transaction; transaction ownership stays with the caller. Used by services/context_vault_service.py.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.error_messages import (
    ERROR_CONTEXT_FACT_NOT_FOUND,
    ERROR_CONTEXT_FACT_REPLACEMENT_NOT_REVERTIBLE,
    ERROR_CONTEXT_FACT_REVISION_CONFLICT,
)
from services.models import ContextFact
from services.repositories.context_fact_repository import (
    _CONTEXT_FACT_LOCK_NAMESPACE,
    _FACT_RETURNING_COLUMNS,
    ContextFactRepository,
)


class ContextFactCurationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 日本語: 事実の書き込みと同じ、トランザクション終了までのユーザー単位ロック。
    # English: The same transaction-scoped per-user lock the fact writes take.
    async def _lock_user_writes(self, user_id: int) -> None:
        await self.session.execute(select(func.pg_advisory_xact_lock(_CONTEXT_FACT_LOCK_NAMESPACE, user_id)))

    # 日本語: 本人の事実の行を FOR UPDATE で読み、revision が expected_revision と一致することを確かめる。無ければ 404、不一致なら 409。
    # English: Reads the owner's fact row FOR UPDATE and checks its revision against expected_revision: 404 when it is missing,
    # 409 on a mismatch.
    async def _lock_fact_row(self, user_id: int, fact_id: int, expected_revision: int) -> Any:
        row = (
            await self.session.execute(
                select(ContextFact.id, ContextFact.status, ContextFact.revision)
                .where(ContextFact.id == fact_id, ContextFact.user_id == user_id)
                .with_for_update()
            )
        ).first()
        if row is None:
            raise ResourceNotFoundError(ERROR_CONTEXT_FACT_NOT_FOUND)
        if int(row.revision) != expected_revision:
            raise ApiServiceError(ERROR_CONTEXT_FACT_REVISION_CONFLICT, 409, status="fail")
        return row

    # 日本語: 置き換えで入った新しい事実を無効化して(理由 user。この内容は再び覚えない)、それが直接置き換えた古い事実を有効へ戻す。
    # 1 トランザクション・ユーザー単位のロックの中で、新しい事実が本人の有効な事実で revision が一致すること、古い事実が本人の無効化済みで
    # 理由 superseded かつ置き換え先が新しい事実であること(直近の 1 件)を確かめてから、2 行を更新する。有効件数は差し引き 0 なので
    # 上限は確認しない。新しい事実の出典は残す。条件に合わなければ何も変えず 404(新しい事実が無い)・409(revision の不一致・状態が変わった)。
    # 戻り値は (無効化した新しい事実, 有効へ戻した古い事実)。
    # English: Deprecates the newer fact that came in by replacement (reason user, so that content is not remembered again) and
    # restores the older fact it directly replaced. Inside one transaction and the per-user lock it checks that the newer fact is
    # the owner's active fact at the given revision and that the older one is the owner's deprecated fact with reason superseded
    # pointing at the newer one (the most recent one), then updates both rows. The active count nets to zero, so the cap is not
    # checked. The newer fact's sources are kept. If a condition fails nothing changes: 404 when the newer fact is missing, 409 for a
    # revision mismatch or a changed state. Returns (the newer fact now deprecated, the older fact made active again).
    async def revert_replacement(
        self, user_id: int, fact_id: int, expected_revision: int
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        await self._lock_user_writes(user_id)
        newer = await self._lock_fact_row(user_id, fact_id, expected_revision)
        if newer.status != "active":
            raise ApiServiceError(ERROR_CONTEXT_FACT_REPLACEMENT_NOT_REVERTIBLE, 409, status="fail")
        older_id = await self.session.scalar(
            select(ContextFact.id)
            .where(
                ContextFact.user_id == user_id,
                ContextFact.status == "deprecated",
                ContextFact.deprecated_reason == "superseded",
                ContextFact.superseded_by_fact_id == fact_id,
            )
            .order_by(ContextFact.updated_at.desc(), ContextFact.id.desc())
            .limit(1)
            .with_for_update()
        )
        if older_id is None:
            raise ApiServiceError(ERROR_CONTEXT_FACT_REPLACEMENT_NOT_REVERTIBLE, 409, status="fail")

        deprecated = await self.session.execute(
            update(ContextFact)
            .where(ContextFact.id == fact_id, ContextFact.user_id == user_id, ContextFact.revision == expected_revision)
            .values(
                status="deprecated",
                deprecated_reason="user",
                superseded_by_fact_id=None,
                revision=ContextFact.revision + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(*_FACT_RETURNING_COLUMNS)
        )
        restored = await self.session.execute(
            update(ContextFact)
            .where(
                ContextFact.id == older_id,
                ContextFact.user_id == user_id,
                ContextFact.status == "deprecated",
                ContextFact.deprecated_reason == "superseded",
                ContextFact.superseded_by_fact_id == fact_id,
            )
            .values(
                status="active",
                deprecated_reason=None,
                superseded_by_fact_id=None,
                revision=ContextFact.revision + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(*_FACT_RETURNING_COLUMNS)
        )
        deprecated_row = deprecated.mappings().first()
        restored_row = restored.mappings().first()
        if deprecated_row is None or restored_row is None:
            raise ApiServiceError(ERROR_CONTEXT_FACT_REPLACEMENT_NOT_REVERTIBLE, 409, status="fail")
        return ContextFactRepository._serialize_row(deprecated_row), ContextFactRepository._serialize_row(restored_row)
