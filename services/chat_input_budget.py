"""最終回答パスへ送るリクエストの入力量を、文字数で数える。生成テレメトリの `final_answer_input_chars` に使う。

Counts the characters in the request sent to the answer pass, for the `final_answer_input_chars` generation telemetry.
"""

from __future__ import annotations

from typing import Any


def estimate_messages_chars(messages: list[dict[str, Any]]) -> int:
    """メッセージ本文の文字数の合計を返す。

    Return the total number of characters in the message bodies.
    """
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        elif content is not None:
            total += len(str(content))
    return total
