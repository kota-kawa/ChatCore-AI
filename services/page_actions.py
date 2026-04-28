from __future__ import annotations

import json
import logging
import re
from typing import Any

from services.agent_capabilities import ALLOWED_AGENT_COMMANDS

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({
    "app_action",
    "click",
    "input",
    "focus",
    "scroll",
    "navigate",
    "select",
    "check",
    "wait",
})

ACTION_SYSTEM_PROMPT = """
ユーザーが現在のページでの画面操作を依頼しています。
提供された機能カタログ、現在のDOM情報、ページのソースコードを参照し、操作手順を特定して、
以下のJSON形式のみで操作手順を返してください（説明文や前置きは不要）：

{
  "description": "操作の概要（1文）",
  "steps": [
    {
      "action": "app_action" | "click" | "input" | "focus" | "scroll" | "navigate" | "select" | "check" | "wait",
      "command": "型付きアクションAPIの command（action=app_actionの場合のみ）",
      "args": {"key": "value"},
      "selector": "CSSセレクタ（navigate/app_action以外で使用。waitは待機対象がある場合）",
      "path": "遷移先パス（action=navigateの場合のみ。例: /settings）",
      "value": "入力値または選択値（action=input/selectの場合のみ）",
      "checked": true,
      "timeout_ms": 1200,
      "risk": "low" | "medium" | "high",
      "description": "このステップの説明"
    }
  ]
}

操作の原則:
- ユーザーの依頼が「入力してからクリック」「ページを開いてから検索」のように複数の画面操作を含む場合は、必ず steps に複数ステップを順番通りに入れる。
- 1ステップには1つの利用者に見える操作だけを入れる。例: input → click、navigate → wait → input → select → check → click のように必要な数だけ並べる。
- 型付きアクションAPIで表現できる単発操作は、action="app_action" を優先する。ただし複数操作を1つの app_action に隠さない。
- select は select 要素の value を変更する。check は checkbox/radio の checked を変更する。wait はクリック後にモーダルや結果が表示されるのを待つ。
- app_action の command はカタログにある command だけを使う。args はカタログの形式に合わせる。
- 現在のDOM情報に一致する要素がある場合は、そこに記載された selector を最優先で使う。
- ページ移動が必要な場合は action="navigate" とし、機能カタログの route または target の相対パスを使う。移動後に続ける操作が明確なら、navigate の後に続きの steps も含める。
- ユーザーが明示した値だけを input の value に入れる。推測した個人情報や危険な値は入力しない。
- 削除、上書き、送信、外部認証など取り消しにくい操作は、ユーザーが明確に依頼した場合だけ含める。
- ログインが必要・画面上に要素がない・状態が不明な場合は、まず該当ページ/タブを開く手順までにする。
- 要素が特定できない場合や操作不可能な場合は steps を空配列にする。

セレクタ選択の優先順位：
1. id属性 (#element-id)
2. data-* 属性 ([data-testid="..."])
3. aria-label属性 ([aria-label="..."])
4. クラス＋タグの組み合わせ (button.submit-btn)
5. 汎用クラス (.class-name)

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
        path = step.get("path", "")
        command = step.get("command", "")
        args = step.get("args", {})
        timeout_ms = step.get("timeout_ms")
        if action not in _VALID_ACTIONS:
            continue
        clean: dict[str, Any] = {
            "action": action,
            "description": str(step.get("description", "")),
        }
        risk = step.get("risk")
        if risk in ("low", "medium", "high"):
            clean["risk"] = risk
        if action == "app_action":
            if command not in ALLOWED_AGENT_COMMANDS:
                continue
            clean["command"] = command
            clean["args"] = args if isinstance(args, dict) else {}
        elif action == "navigate":
            if not isinstance(path, str) or not path.startswith("/"):
                continue
            clean["path"] = path
        elif action == "wait":
            if selector:
                clean["selector"] = selector
            if isinstance(timeout_ms, int | float):
                clean["timeout_ms"] = max(0, min(int(timeout_ms), 5000))
            elif not selector:
                clean["timeout_ms"] = 300
        else:
            if not selector:
                continue
            clean["selector"] = selector
        if action in ("input", "select"):
            clean["value"] = str(step.get("value", ""))
        if action == "check":
            clean["checked"] = bool(step.get("checked", True))
        valid_steps.append(clean)

    if not valid_steps:
        return None

    return {
        "description": str(data.get("description", "操作を実行します")),
        "steps": valid_steps,
    }
