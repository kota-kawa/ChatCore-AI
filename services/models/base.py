"""アプリと Alembic が共有する、SQLAlchemy モデルの土台（宣言的基底クラス）。

SQLAlchemy model foundation shared by the application and Alembic.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """ChatCore が持つすべての PostgreSQL テーブルの宣言的基底クラス。

    Declarative base for every PostgreSQL table owned by ChatCore.
    """
