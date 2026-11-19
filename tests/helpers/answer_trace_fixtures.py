"""回答の実行記録（「回答までのステップ」）の見本データを読むテスト用ヘルパー。

``tests/fixtures/answer_trace/`` には、同じ内容の実行記録が 2 つの形で入っている。``<name>.json`` は回答パーツとして
保存・配信する構造化データ、``<name>_legacy.html`` は構造化する前に本文の先頭へ保存していた HTML で、当時の実装が
出力したもの。旧形式の回答を読む処理のテストと、画面の描画が旧形式と一致することの確認に使う。

Test helper that loads sample execution records (the "steps to the answer").

``tests/fixtures/answer_trace/`` holds the same record in two shapes. ``<name>.json`` is the structured data
stored and delivered as an answer part; ``<name>_legacy.html`` is the markup that used to be saved at the head of
the body, as produced by the implementation of that time. They back the tests for reading legacy answers and the
check that the screen renders the same as the legacy markup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "answer_trace"


def load_answer_trace(name: str) -> dict[str, Any]:
    """構造化した実行記録の見本を読む。 / Load a sample structured execution record."""
    return json.loads((_FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def load_legacy_answer_trace_html(name: str) -> str:
    """構造化前の実行記録の HTML の見本を読む。 / Load sample pre-structuring execution-record markup."""
    return (_FIXTURE_DIR / f"{name}_legacy.html").read_text(encoding="utf-8").rstrip("\n")
