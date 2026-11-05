"""データベースの疎通と、アプリのスキーマが使えるかを確かめる最小限のクエリ。

services/health.py から使われる。

Database readiness probes executed through SQLAlchemy Core.
Used by services/health.py.
"""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import User


class HealthRepository:
    # アプリのスキーマ検証に必要な最小限のクエリを実行する。
    """Run the minimal queries needed to validate the application schema."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 日本語: users テーブルを読んで基本スキーマの存在を、SELECT 1 で接続自体を確認する。失敗は例外として呼び出し側に伝わる。
    # English: Reading users confirms the base schema exists and SELECT 1 confirms the connection; failures propagate as exceptions.
    async def check_database(self) -> None:
        await self.session.scalar(select(func.count()).select_from(User))
        await self.session.scalar(text("SELECT 1"))
