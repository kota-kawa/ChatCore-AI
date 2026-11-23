"""モデルへ渡す文字列を、長さの上限に合わせて切り詰める。

Truncate a string to a length limit before it is handed to the model.
"""

from __future__ import annotations


# 前後の空白を除き、limit 文字を超えたら切り詰めて「…」を付ける。None は空文字として扱う。
# Strip whitespace and, when longer than limit characters, truncate with an ellipsis. None counts as an empty string.
def trim_text(text: str, limit: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}…"
