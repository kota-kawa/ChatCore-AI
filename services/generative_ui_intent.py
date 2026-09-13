# 生成UIの「作らない」判断を、LLMの判定結果とユーザーの明示的な拒否に分ける。
# 判定モデルが NONE を返しただけで、既に生成された安全なArtifactまで捨てると、
# 判定の偽陰性がそのまま利用者から見た失敗になる。ここで扱うのは
# 「ユーザー自身がUI不要と書いたか」だけで、UIモードそのものの推定は行わない。
# Separates "no generated UI" decided by the classifier from a refusal the user wrote
# themselves. Discarding an already-validated artifact merely because the classifier
# returned NONE turns every false negative into a user-visible failure. This module only
# answers "did the user explicitly ask for no UI?" and never infers the UI mode itself.

from __future__ import annotations

import re
from typing import Any

from services.user_skills import (
    GENERATIVE_UI_ARTIFACT_BLOCK_CONTRACT,
    GENERATIVE_UI_ARTIFACT_JSON_CONTRACT,
    GENERATIVE_UI_ARTIFACT_PRESENTATION_FIELDS,
    GENERATIVE_UI_THREE_LIBRARY_CONTRACT,
)

# 「UI・図を作らない」と読める表現だけを拾う。UIについて説明を求める文とは区別する。
# Match only phrasings that refuse a visual, never a request to explain one.
_UI_NOUN = r"(?:生成\s*UI|UI|ユーザーインターフェース|図|図解|グラフ|チャート|ビジュアル|可視化|アニメーション|3\s*D)"
_JA_REFUSAL = r"(?:いらない|いりません|不要|要らない|使わ(?:ず|ない)|作ら(?:ず|ないで|なくて)|なし(?:で|に)|抜きで|禁止)"
_EXPLICIT_OPT_OUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 日本語: UIを表す語の直後（読点や助詞を挟む程度）に否定が来る場合のみ拒否と見なす。
    # Japanese: a refusal counts only when it follows a visual noun closely.
    re.compile(_UI_NOUN + r"[^。．\n]{0,12}?" + _JA_REFUSAL),
    re.compile(r"(?:テキスト|文章|文字|言葉)(?:だけ|のみ)"),
    re.compile(
        r"(?:no|without|skip|avoid)\s+(?:a\s+|an\s+|any\s+)?"
        r"(?:ui|user\s+interface|diagram|chart|graph|visual|visualization|animation|3d)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:text|prose|words|writing)[\s-]*only", re.IGNORECASE),
    re.compile(r"(?:in|as)\s+(?:plain\s+)?(?:text|prose)\s+only", re.IGNORECASE),
    re.compile(
        r"(?:do\s+not|don't|no\s+need\s+to)\s+(?:create|generate|build|make|render|show)\s+"
        r"(?:a\s+|an\s+|any\s+)?(?:ui|diagram|chart|graph|visual|visualization|animation|3d)",
        re.IGNORECASE,
    ),
)

# 判定済みモードは本体生成のプロンプトへ必ず注入する。判定と本体で二重に推測させると、
# 判定は 2D、本体は散文という食い違いが起き、後段が本文ごと捨てる経路が生まれる。
# The decided mode is injected into the generation prompt. Letting the classifier and the
# answering pass guess independently produces "classified 2D, answered in prose", which the
# later stages can only resolve by discarding output.
# 出力契約そのものは Skill（services/user_skills.py）が正本。ここは「どのモードに確定したか」と
# その必須性だけを足す。
# The output contract itself belongs to the Skill (services/user_skills.py); this adds only the
# decided mode and the fact that it is now required.
_MODE_INSTRUCTION = (
    "Generated UI mode for this turn is already decided: {mode}. The decision is final; do not "
    "re-evaluate it. " + GENERATIVE_UI_ARTIFACT_BLOCK_CONTRACT
    + " It is required in this answer, after a short prose introduction. "
    + GENERATIVE_UI_ARTIFACT_JSON_CONTRACT + " "
    + GENERATIVE_UI_ARTIFACT_PRESENTATION_FIELDS + " {mode_requirement}"
)
_MODE_REQUIREMENTS = {
    "2D": (
        "Build a complete, responsive 2D interface with meaningful initial content; do not use "
        "Three.js or WebGL."
    ),
    "3D": (
        GENERATIVE_UI_THREE_LIBRARY_CONTRACT
        + " Build a complete scene with a renderer, camera, lighting, and visible geometry."
    ),
}
_INJECTABLE_MODES = frozenset(_MODE_REQUIREMENTS)


def is_explicit_generative_ui_opt_out(text: Any) -> bool:
    """Return whether the user themselves refused a generated UI.

    判定モデルの NONE はここには含めない。明示的な拒否だけが、検証済みArtifactを
    破棄してよい唯一の根拠になる。
    A classifier's NONE never reaches this function. Only an explicit refusal justifies
    discarding an artifact that already passed validation.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    normalized = text.strip()
    return any(pattern.search(normalized) for pattern in _EXPLICIT_OPT_OUT_PATTERNS)


def inject_generative_ui_mode_instruction(
    conversation_messages: list[dict[str, Any]],
    mode: str | None,
) -> list[dict[str, Any]]:
    """Return a copy of the conversation carrying the decided UI mode as a requirement.

    元のリストとメッセージ辞書は変更しない。モードが 2D/3D 以外のときは複製だけを返す。
    Neither the list nor its message dicts are mutated. Modes other than 2D/3D return a copy.
    """
    messages = [dict(message) for message in conversation_messages or []]
    normalized_mode = str(mode or "").strip().upper()
    if normalized_mode not in _INJECTABLE_MODES:
        return messages
    messages.append(
        {
            "role": "system",
            "content": _MODE_INSTRUCTION.format(
                mode=normalized_mode,
                mode_requirement=_MODE_REQUIREMENTS[normalized_mode],
            ),
        }
    )
    return messages
