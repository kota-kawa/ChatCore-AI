"""Tools that let the chat model read and write the user's own data, one family at a time.

ファミリーごとの既定スキル（「メモ」など）が ON のときだけ、そのツールを生成ループへ渡す。
A family's tools reach the generation loop only while its built-in Skill (such as "Memo") is on.
"""

from __future__ import annotations

from .memo import MEMO_TOOL_SPECS
from .registry import ChatWorkspaceToolbox, ToolSpec

WORKSPACE_TOOL_SPECS: dict[str, ToolSpec] = {spec.name: spec for spec in MEMO_TOOL_SPECS}


def get_workspace_tool_spec(name: str) -> ToolSpec | None:
    return WORKSPACE_TOOL_SPECS.get(name)


# 1ターン分のツールボックスを作る。ログイン利用者の通常ルームで、対応する既定スキルが ON の
# ときだけ呼ぶ前提で、渡すツールが1つも無ければ None を返す。
# Build the toolbox for one turn. Callers invoke it only for a signed-in user's normal room;
# it returns None when no family is enabled.
def build_workspace_toolbox(
    *,
    user_id: int,
    chat_room_id: str,
    memo_tools_enabled: bool,
    external_input_in_turn: bool,
) -> ChatWorkspaceToolbox | None:
    specs = [*MEMO_TOOL_SPECS] if memo_tools_enabled else []
    if not specs:
        return None
    return ChatWorkspaceToolbox(
        specs,
        user_id=user_id,
        chat_room_id=chat_room_id,
        external_input_in_turn=external_input_in_turn,
    )
