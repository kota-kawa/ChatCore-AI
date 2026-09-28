"""Tools that let the chat model read and write the user's own data, one family at a time.

プロフィール設定ツールはログイン利用者の通常チャットで常に渡し、メモと Prompt/Skill のツールは
それぞれの既定 Skill が ON のときだけ生成ループへ渡す。
Profile settings are always available to a signed-in user's normal chat; memo and Prompt/Skill
tools still follow their respective built-in Skill toggles.
"""

from __future__ import annotations

from .memo import MEMO_TOOL_SPECS
from .profile import PROFILE_TOOL_SPECS
from .prompts import PROMPTS_TOOL_SPECS
from .registry import ChatWorkspaceToolbox, ToolSpec

WORKSPACE_TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec for spec in (*PROFILE_TOOL_SPECS, *MEMO_TOOL_SPECS, *PROMPTS_TOOL_SPECS)
}


def get_workspace_tool_spec(name: str) -> ToolSpec | None:
    return WORKSPACE_TOOL_SPECS.get(name)


# 1ターン分のツールボックスを作る。ログイン利用者の通常ルームで呼ぶ前提。プロフィールツールは
# 常時含め、メモと Prompt/Skill は各スキルの状態に従う。
# Build the toolbox for one turn. Callers invoke it only for a signed-in user's normal room;
# profile tools are always present, while memo and Prompt/Skill tools follow their own toggles.
def build_workspace_toolbox(
    *,
    user_id: int,
    chat_room_id: str,
    memo_tools_enabled: bool,
    prompt_tools_enabled: bool = False,
    external_input_in_turn: bool,
    llm_profile_context: str = "",
    browser_theme_preference: str | None = None,
) -> ChatWorkspaceToolbox | None:
    specs = [
        *PROFILE_TOOL_SPECS,
        *(MEMO_TOOL_SPECS if memo_tools_enabled else ()),
        *(PROMPTS_TOOL_SPECS if prompt_tools_enabled else ()),
    ]
    return ChatWorkspaceToolbox(
        specs,
        user_id=user_id,
        chat_room_id=chat_room_id,
        external_input_in_turn=external_input_in_turn,
        llm_profile_context=llm_profile_context,
        browser_theme_preference=browser_theme_preference,
    )
