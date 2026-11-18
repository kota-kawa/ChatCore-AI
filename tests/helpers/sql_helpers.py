"""SQL 文を検証するテスト用の共通ヘルパー。

Shared helpers for tests that assert on SQL statements.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.sql.elements import ClauseElement


def bind_statement_parameters(statement: ClauseElement) -> dict[str, Any]:
    """PostgreSQL 向けにコンパイルし、各パラメータを実行時と同じ型変換に通した値を返す。

    コンパイルした文字列を見るだけでは、パラメータが誤った型で束縛されて実行時に落ちる不具合を検出できない。

    Compile for PostgreSQL and return every parameter after the same type conversion execution applies.

    Inspecting the compiled string alone cannot catch a parameter bound with the wrong type, which only fails at execution.
    """
    postgresql = dialect()
    compiled = statement.compile(dialect=postgresql)
    bound: dict[str, Any] = {}
    for parameter, name in compiled.bind_names.items():
        process = parameter.type.dialect_impl(postgresql).bind_processor(postgresql)
        value = parameter.effective_value
        bound[name] = process(value) if process else value
    return bound
