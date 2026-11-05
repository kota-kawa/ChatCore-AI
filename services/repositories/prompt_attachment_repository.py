"""プロンプトの添付ファイルの参照情報を読み出す永続化処理。

services/prompt_attachment_cleanup.py の添付ファイル突き合わせ(DB 上の参照と実ファイルの照合)で使われる。

Persistence for prompt attachment references.
Used by the attachment reconciliation in services/prompt_attachment_cleanup.py.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Prompt


class PromptAttachmentRepository:
    """ファイル突き合わせジョブが使う添付ファイルのメタデータを読み出す。

    Read attachment metadata used by the file reconciliation job.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 日本語: 削除されていないプロンプトの attachments 配列を 1 つのリストに平坦化して返す(dict 以外の要素は捨てる)。
    # English: Flattens the attachments arrays of non-deleted prompts into one list, dropping non-dict items.
    async def list_active_attachments(self) -> list[dict[str, Any]]:
        values = await self.session.scalars(
            select(Prompt.attachments).where(
                Prompt.deleted_at.is_(None),
                Prompt.attachments.is_not(None),
            )
        )
        attachments: list[dict[str, Any]] = []
        for value in values:
            if isinstance(value, list):
                attachments.extend(item for item in value if isinstance(item, dict))
        return attachments
