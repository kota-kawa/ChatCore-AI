# 生成UIの修復要求を、通常回答のプロンプトから切り離して組み立てる。
# 修復を会話履歴ごと送ると、TurnState更新やツール規約といった別プロトコルの指示が
# 「Artifactだけ返せ」という指示と同居し、弱いモデルほどどちらも崩す。ここでは
# 「ユーザーの要求・確定モード・理由コード・直前の出力」だけを渡す。
# Builds the repair request separately from the normal answering prompt. Sending the whole
# conversation makes the TurnState and tool protocols compete with "return only an artifact",
# and weaker models then break both. Only the user request, the decided mode, the reason
# codes, and the previous output are passed here.

from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import partial
from typing import Any, Literal

# 修復も本文を書くフェーズ。既定の小さい出力枠のままだと修復自体が途中で切れ、
# 「修復しても直らなかった」という誤った結論になる。
# Repair writes a body too. Leaving it on the smaller default budget truncates the repair
# itself and produces the false conclusion that repair did not help.
ANSWER_GENERATION_PHASE = "final_answer"

# 仕上がりの粗さだけを示す指摘。これだけなら、修復結果でも採用してよい。
# Issues that only indicate rough polish; a repaired artifact may still be accepted.
_POLISH_ONLY_ISSUE_MARKERS = (
    "presentation styling is too sparse",
    "implementation is too small",
)
MAX_REPORTED_ISSUES = 8
MAX_PREVIOUS_OUTPUT_CHARS = 16000
MAX_INTENT_CHARS = 8000

_MODE_REQUIREMENTS = {
    "3D": (
        "Include libraries:[\"three\"] and use the existing global THREE. Build a complete scene "
        "with renderer, camera, lighting, visible geometry, polished materials, a fitted "
        "composition, capped pixel ratio, resize handling, and useful pointer interaction."
    ),
    "2D": (
        "Build a complete responsive product-style UI with meaningful initial content, clear "
        "visual hierarchy, deliberate spacing and typography, strong contrast, and interaction "
        "when it helps the requested task. Do not return a prose card or a lightly styled table."
    ),
}


def has_blocking_quality_issue(issues: list[str]) -> bool:
    """Whether the issues describe a broken result rather than a rough one.

    描画できない・実行できない結果を「直った」として採用しないための判定。
    Keeps a result that cannot render or run from being reported as repaired.
    """
    return any(
        not any(marker in issue for marker in _POLISH_ONLY_ISSUE_MARKERS)
        for issue in issues
    )


def build_artifact_repair_messages(
    *,
    raw_text: str,
    intent_text: str,
    mode: Literal["2D", "3D"],
    reason_codes: list[str],
    issues: list[str],
) -> list[dict[str, Any]]:
    """Build a self-contained repair prompt with no competing turn protocols."""
    issue_lines = "\n".join(f"- {issue}" for issue in issues[:MAX_REPORTED_ISSUES])
    code_line = ", ".join(dict.fromkeys(code for code in reason_codes if code)) or "artifact_invalid"
    repair_prompt = (
        "Your previous generated-UI answer failed the application's completion or quality gate. "
        "Regenerate the user's requested result now. Preserve the user's subject, data, language, "
        "and intent; improve only the implementation.\n\n"
        f"Required mode: {mode}\n"
        f"Failure codes: {code_line}\n"
        f"Detected problems:\n{issue_lines}\n\n"
        f"{_MODE_REQUIREMENTS[mode]}\n"
        "Return exactly one complete ```chatcore-artifact fenced block and no separate HTML, CSS, "
        "JavaScript, JSON, explanation, turn-state update, tool call, or UI_MODE text. The block "
        "must hold one valid JSON object containing version, title, description, height, html, css, "
        "and js, with every embedded quote, newline, and backslash escaped so the block parses as "
        "valid JSON. The html must contain id=\"app\" and the js must be syntactically complete. "
        "Use no network, external resources, imports, storage, or parent-page access. Keep the "
        "result compact enough to finish, and include the closing brace and closing fence."
    )
    messages: list[dict[str, Any]] = []
    if raw_text.strip():
        messages.append({"role": "assistant", "content": raw_text[-MAX_PREVIOUS_OUTPUT_CHARS:]})
    messages.append({"role": "system", "content": repair_prompt})
    # 元の要求を最後に置き、プロバイダの言語選択と主題の根拠を英語の修復指示ではなく
    # ユーザー本文に置く。
    # Repeat the original request last so provider language selection and subject grounding
    # come from the user, not from the English repair instruction.
    messages.append({"role": "user", "content": intent_text[-MAX_INTENT_CHARS:]})
    return messages


def with_answer_output_budget(
    generate_response: Callable[..., str | None],
) -> Callable[..., str | None]:
    """Bind the answer-phase output budget when the provider call accepts a phase."""
    try:
        parameters = inspect.signature(generate_response).parameters
    except (TypeError, ValueError):
        return generate_response
    if "generation_phase" not in parameters:
        return generate_response
    return partial(generate_response, generation_phase=ANSWER_GENERATION_PHASE)
