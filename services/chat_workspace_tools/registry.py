"""Shapes shared by the chat workspace tools and the per-turn toolbox handed to generation.

チャットから利用者自身のデータ（メモなど）を読み書きするツールの共通の形を持つ。
読み取りツールはその場で実行し、書き込みツールは「提案」だけを作って承認カードへ回す。
実行は承認後にサーバーが行う（services/chat_tool_approval_service.py）。
Holds the shared shapes of the tools that read and write the user's own data (memos and
so on) from chat. Read tools run on the spot; write tools only build a proposal that becomes
an approval card, and the server runs it after the user approves
(services/chat_tool_approval_service.py).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

# ツールがどの予算を使うか。検索系は tool_calls、範囲読み取りは reads、書き込みの提案は
# write_proposals を消費する（services/chat_agent_budget.py）。
# Which budget a tool draws from: searches use tool_calls, ranged reads use reads, and write
# proposals use write_proposals (services/chat_agent_budget.py).
ToolBudget = Literal["tool_calls", "reads", "write_proposals"]


class WorkspaceToolArgumentError(ValueError):
    """The model's arguments are unusable; ``problems`` goes back to the model as is."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


class WorkspaceToolError(Exception):
    """A tool could not run for a reason the card or the model sees only as a code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# 読み取りツールの結果。query は TurnState の実行記録に残す検索語。
# A read tool's result; query is what TurnState records as the lookup.
@dataclass(frozen=True)
class ReadResult:
    payload: dict[str, Any]
    query: str = ""


# 書き込みツールの提案。arguments は承認後の実行に使う引数の写し、preview はカードに
# 出す変更内容、target_ref は提案時の対象（ID・版・共有中か）。
# A write tool's proposal: arguments is the snapshot the approved run uses, preview is the
# change shown on the card, and target_ref is the target as proposed (id, revision, shared).
@dataclass(frozen=True)
class Proposal:
    arguments: dict[str, Any]
    preview: dict[str, Any]
    target_ref: dict[str, Any]
    target_title: str
    shared: bool = False


# 実行結果。after_commit は確定後に走らせる処理（メモの埋め込み予約など）。
# The outcome of a run; after_commit runs once the transaction has committed (such as
# scheduling a memo embedding).
@dataclass(frozen=True)
class ExecutionOutcome:
    target_id: int
    target_title: str
    after_commit: Callable[[], None] | None = None


ReadHandler = Callable[[int, dict[str, Any], int], Awaitable[ReadResult]]
ProposeHandler = Callable[[int, dict[str, Any]], Awaitable[Proposal]]
ExecuteHandler = Callable[[AsyncSession, int, dict[str, Any], dict[str, Any]], Awaitable[ExecutionOutcome]]


# ツール1つの定義。definition はモデルへ見せるスキーマ（制約は誘導であり、検証はハンドラの
# Pydantic が行う。ADR 0008）。allows_always は「常に承認」を付与できるか。
# One tool. definition is the schema shown to the model (its constraints guide, the handler's
# Pydantic validates; ADR 0008). allows_always says whether "always approve" may be granted.
@dataclass(frozen=True)
class ToolSpec:
    name: str
    family: str
    definition: dict[str, Any]
    budget: ToolBudget
    read: ReadHandler | None = None
    propose: ProposeHandler | None = None
    execute: ExecuteHandler | None = None
    allows_always: bool = False

    @property
    def is_write(self) -> bool:
        return self.budget == "write_proposals"


# 1ターン分のツール一式。ターンの途中で一覧を変えない（ADR 0011）ため、並びは定義順で固定する。
# ツールは利用者 ID に束ねてあり、モデルの引数に user_id は現れない。
# The tools for one turn. The list never changes mid-turn (ADR 0011), so the order is fixed
# by definition order. Tools are bound to the user id; no model argument carries a user_id.
class ChatWorkspaceToolbox:
    def __init__(
        self,
        specs: Sequence[ToolSpec],
        *,
        user_id: int,
        chat_room_id: str,
        external_input_in_turn: bool = False,
    ) -> None:
        self._specs = {spec.name: spec for spec in specs}
        self.user_id = int(user_id)
        self.chat_room_id = chat_room_id
        # 添付・貼り付け URL・他人の公開投稿など、ターンの開始時点で外部の内容を読んでいるか。
        # Whether the turn starts having read external content: attachments, pasted URLs,
        # other people's public posts.
        self.external_input_in_turn = bool(external_input_in_turn)

    def definitions(self) -> list[dict[str, Any]]:
        return [spec.definition for spec in self._specs.values()]

    def handles(self, name: Any) -> bool:
        return isinstance(name, str) and name in self._specs

    def spec(self, name: str) -> ToolSpec:
        return self._specs[name]

    def is_write(self, name: Any) -> bool:
        return self.handles(name) and self._specs[name].is_write

    def uses_read_budget(self, name: Any) -> bool:
        return self.handles(name) and self._specs[name].budget == "reads"


# モデルが返した引数の文字列を辞書にする。JSON でなければ、直せる問題としてモデルへ返す。
# Turn the model's argument string into a dict; anything else is a fixable problem for the model.
def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        raise WorkspaceToolArgumentError(("Tool arguments must be a JSON object.",)) from None
    if not isinstance(parsed, dict):
        raise WorkspaceToolArgumentError(("Tool arguments must be a JSON object.",))
    return parsed


# Pydantic の検証エラーを、モデルが読んで直せる短い文の並びにする。
# Turn a Pydantic validation error into short sentences the model can act on.
def validation_problems(exc: ValidationError) -> tuple[str, ...]:
    problems: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "__root__")
        message = str(error.get("msg") or "is invalid")
        problems.append(f"{location}: {message}" if location else message)
    return tuple(problems) or ("Tool arguments are invalid.",)
