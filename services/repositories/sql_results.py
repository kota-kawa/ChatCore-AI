"""リポジトリが SQL の実行結果から値を読むための小さな共通関数。

Small helpers shared by repositories for reading values out of SQL execution results.
"""

from __future__ import annotations

from typing import Any


def affected_row_count(result: Any) -> int:
    # PostgreSQLの更新結果から影響行数を読む。
    """Read the affected-row count exposed by PostgreSQL DML results."""
    return int(getattr(result, "rowcount", 0) or 0)
