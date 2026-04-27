from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({"click", "input", "focus", "scroll"})

ACTION_SYSTEM_PROMPT = """
ユーザーが現在のページでの画面操作を依頼しています。
提供されたページのソースコードを参照し、操作可能な要素のCSSセレクタを特定して、
以下のJSON形式のみで操作手順を返してください（説明文や前置きは不要）：

{
  "description": "操作の概要（1文）",
  "steps": [
    {
      "action": "click" | "input" | "focus" | "scroll",
      "selector": "CSSセレクタ",
      "value": "入力値（action=inputの場合のみ）",
      "description": "このステップの説明"
    }
  ]
}

セレクタ選択の優先順位：
1. id属性 (#element-id)
2. data-* 属性 ([data-testid="..."])
3. aria-label属性 ([aria-label="..."])
4. クラス＋タグの組み合わせ (button.submit-btn)
5. 汎用クラス (.class-name)

要素が特定できない場合や操作不可能な場合は steps を空配列にしてください。
""".strip()


def build_action_messages(
    page_context: str,
    conversation_messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    system_content = f"{ACTION_SYSTEM_PROMPT}\n\n{page_context}"
    return [{"role": "system", "content": system_content}, *conversation_messages]


def parse_action_response(text: str) -> dict[str, Any] | None:
    """AIレスポンスからJSON操作計画を抽出して検証する。"""
    if not text:
        return None

    # マークダウンコードフェンスがあれば内側を取り出す
    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = code_block.group(1) if code_block else text

    json_match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if not json_match:
        return None

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        logger.warning("Failed to parse action response as JSON")
        return None

    if not isinstance(data.get("steps"), list):
        return None

    valid_steps: list[dict[str, Any]] = []
    for step in data["steps"]:
        if not isinstance(step, dict):
            continue
        action = step.get("action", "")
        selector = step.get("selector", "")
        if action not in _VALID_ACTIONS or not selector:
            continue
        clean: dict[str, Any] = {
            "action": action,
            "selector": selector,
            "description": str(step.get("description", "")),
        }
        if action == "input":
            clean["value"] = str(step.get("value", ""))
        valid_steps.append(clean)

    if not valid_steps:
        return None

    return {
        "description": str(data.get("description", "操作を実行します")),
        "steps": valid_steps,
    }
