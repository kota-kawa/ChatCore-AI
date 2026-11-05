"""モデルのメタデータが使う、PostgreSQL 固有の SQLAlchemy 型（pgvector の ``vector(n)``）。

PostgreSQL-specific SQLAlchemy types used by the model metadata.
"""

from __future__ import annotations

import ast
from typing import Any

from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType):
    """PostgreSQL の拡張型 ``vector(n)`` 用の小さな SQLAlchemy 型。

    このプロジェクトに必要なのは、コサイン距離の式と埋め込みの往復変換だけである。型を自前で持てば、
    別の ORM 連携パッケージを増やさずに、SQLAlchemy/Alembic に正確な PostgreSQL の型を出力させられる。

    A small SQLAlchemy type for the PostgreSQL ``vector(n)`` extension type.

    The project only needs cosine-distance expressions and round-tripping of
    model embeddings.  Keeping this type local avoids adding a second ORM
    integration package while still allowing SQLAlchemy/Alembic to render the
    exact PostgreSQL type.
    """

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dimensions})"

    def bind_processor(self, _dialect: Any):
        # Python の数値列を pgvector のテキスト表現 "[x,y,...]" に変換して DB へ渡す。文字列はそのまま通す。
        # Convert a Python number sequence to pgvector's text form "[x,y,...]" for the database; strings pass through.
        def process(value: Any) -> str | None:
            if value is None:
                return None
            if isinstance(value, str):
                return value
            return "[" + ",".join(format(float(item), ".9g") for item in value) + "]"

        return process
    def result_processor(self, _dialect: Any, _coltype: Any):
        # DB から返った pgvector の値（"[x,y,...]" の文字列など）を float のリストに戻す。
        # Convert the value returned by the database (such as the "[x,y,...]" string) back to a list of floats.
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return [float(item) for item in value]
            raw = str(value).strip()
            if raw.startswith("[") and raw.endswith("]"):
                try:
                    parsed = ast.literal_eval(raw)
                except (SyntaxError, ValueError):
                    parsed = [item for item in raw[1:-1].split(",") if item]
                return [float(item) for item in parsed]
            return [float(item) for item in raw.split(",") if item]

        return process
