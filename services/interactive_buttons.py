# チャットの選択ボタン（Yes/No・単一選択・複数選択）の契約を持つ。
# 選択ボタンは生成UIではなくチャット標準の表示部品で、生成UIの Skill の有無やモード判定、
# 利用者の「UI不要」に関係なく表示する。検索画像や生成UIとも同じ返信に並べられる。
# Owns the contract of chat choice buttons (yes/no, single choice, multiple select).
# They are a standard chat display part rather than a generated UI, so they are shown
# whatever the generated-UI Skill, the mode decision, or a user's "no UI" says, and they
# can share a reply with web-search images or a generated UI.

from __future__ import annotations

import re
from html import escape as escape_html
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

INTERACTIVE_BUTTONS_PART_TYPE = "interactive_buttons"
# 旧来の別名（interactive-buttons / interactive_buttons）も読み、本文へJSONを漏らさない。
# Legacy aliases are still read so their JSON never leaks into the prose.
INTERACTIVE_BUTTONS_BLOCK_RE = re.compile(
    r"```(?:chatcore-buttons|interactive-buttons|interactive_buttons)(?:\s+json)?\s*"
    r"(?P<json>\{[\s\S]*?\})\s*```",
    re.IGNORECASE,
)
# 上限はモデルに見せる説明（services/chat_prompt.py の「Choice buttons」）と揃える。
# The limits match the model-facing description ("Choice buttons" in services/chat_prompt.py).
MAX_INTERACTIVE_BUTTONS_QUESTION_CHARS = 500
MAX_INTERACTIVE_BUTTON_OPTIONS = 10
MIN_MULTIPLE_SELECT_OPTIONS = 2
MAX_INTERACTIVE_BUTTON_BLOCKS_PER_MESSAGE = 3


class InteractiveButtonsValidationError(ValueError):
    """Raised when a choice-buttons payload does not satisfy the contract."""


# 選択ボタン1組のスキーマ。yes_no は選択肢を持たず、表示側が「はい／いいえ」を出す。
# 単一選択は1つ以上、複数選択は2つ以上の選択肢が要る（1つだけの複数選択は選ぶ意味がない）。
# Schema of one set of choice buttons. yes_no carries no options; the client shows yes/no.
# A single choice needs at least one option and a multiple select at least two, because a
# one-item multiple select offers nothing to choose.
class InteractiveButtonsV1(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    type: Literal["yes_no", "multiple_choice", "multiple_select"]
    question: str = Field(min_length=1, max_length=MAX_INTERACTIVE_BUTTONS_QUESTION_CHARS)
    options: list[str] | None = Field(default=None, max_length=MAX_INTERACTIVE_BUTTON_OPTIONS)

    # 空の選択肢と重複を除いてから必要数を確かめる。先に数えると空文字だけの選択肢が通る。
    # Drop blank and duplicate options before counting; counting first lets blanks through.
    @model_validator(mode="after")
    def _normalize_options(self) -> InteractiveButtonsV1:
        if self.type == "yes_no":
            self.options = None
            return self
        options = list(dict.fromkeys(option for option in self.options or [] if option))
        minimum = MIN_MULTIPLE_SELECT_OPTIONS if self.type == "multiple_select" else 1
        if len(options) < minimum:
            raise ValueError(f"{self.type} needs at least {minimum} non-empty options")
        self.options = options
        return self


# 選択ボタンの定義を検証し、保存・配信する形の辞書で返す。
# Validate a choice-buttons payload and return the dict that is stored and delivered.
def validate_interactive_buttons_payload(payload: Any) -> dict[str, Any]:
    try:
        buttons = InteractiveButtonsV1.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        raise InteractiveButtonsValidationError(str(exc)) from exc
    return buttons.model_dump(exclude_none=True)


# 検証済みの選択ボタンを、メッセージの表示部品へ変換する。
# Turn validated choice buttons into message display parts.
def interactive_buttons_parts(buttons_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"type": INTERACTIVE_BUTTONS_PART_TYPE, "buttons": buttons} for buttons in buttons_list]


# 後続ターンのモデル文脈へ渡す、選択ボタンの要約行を作る。利用者の次の発話が
# どの問いへの回答か（複数選択なら複数の選択肢を並べた回答か）を読めるようにする。
# Build the summary lines handed to later turns so the model can tell which question the
# user's next message answers, including a multiple select answered with several labels.
def describe_interactive_buttons_for_context(buttons: Any) -> list[str]:
    if not isinstance(buttons, dict):
        return []
    question = str(buttons.get("question") or "").strip()
    if not question:
        return []
    button_type = str(buttons.get("type") or "").strip()
    lines = [
        f'<interactive_buttons type="{escape_html(button_type)}">',
        f"<question>{escape_html(question)}</question>",
    ]
    options = buttons.get("options")
    if isinstance(options, list):
        labels = [str(option).strip() for option in options if str(option).strip()]
        if labels:
            lines.append(f"<options>{escape_html(' | '.join(labels))}</options>")
    lines.append("</interactive_buttons>")
    return lines
