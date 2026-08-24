"""PostgreSQL-specific SQLAlchemy types used by the model metadata."""

from __future__ import annotations

import ast
from typing import Any

from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType):
    """A small SQLAlchemy type for the PostgreSQL ``vector(n)`` extension type.

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
        def process(value: Any) -> str | None:
            if value is None:
                return None
            if isinstance(value, str):
                return value
            return "[" + ",".join(format(float(item), ".9g") for item in value) + "]"

        return process
    def result_processor(self, _dialect: Any, _coltype: Any):
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
