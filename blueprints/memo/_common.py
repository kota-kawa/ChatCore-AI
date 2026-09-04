from __future__ import annotations

import sys
from typing import Any


def _memo_attr(name: str) -> Any:
    """
    メモモジュールから動的に属性を取得するヘルパー関数（循環参照防止）
    Helper to dynamically retrieve an attribute from the memo package to prevent circular imports.

    Args:
        name (str): 属性名 / Attribute name to retrieve.

    Returns:
        Any: 取得された属性 / The retrieved attribute.
    """
    return getattr(sys.modules["blueprints.memo"], name)
