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

from services.chat_prompt import insert_before_latest_user_message
from services.structured_ui_prompt import STRUCTURED_UI_EXECUTION_CONTRACT

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
_ARTIFACT_INSTRUCTIONS = {
    "2D": (
        "A complete chatcore-artifact block is required: produce exactly one ```chatcore-artifact "
        "fenced JSON block in addition to a short "
        "prose introduction. The JSON must contain version, title, description, height, html, css, "
        "and js, and html must contain id=\"app\". Build a complete, responsive 2D interface with "
        "meaningful initial content; do not use Three.js or WebGL."
    ),
    "3D": (
        "A complete chatcore-artifact block is required: produce exactly one ```chatcore-artifact "
        "fenced JSON block in addition to a short "
        "prose introduction. The JSON must contain version, title, description, height, html, css, "
        "and js, and html must contain id=\"app\". Declare libraries:[\"three\"] and build a complete "
        "Three.js scene with a renderer, camera, lighting, and visible geometry using the existing "
        "global THREE."
    ),
}
_MODE_INSTRUCTIONS = {
    "STRUCTURED_UI": STRUCTURED_UI_EXECUTION_CONTRACT,
    **_ARTIFACT_INSTRUCTIONS,
    "MIXED_2D": (
        "Produce both at least one native structured UI block and exactly one complete 2D "
        "chatcore-artifact block. "
        + STRUCTURED_UI_EXECUTION_CONTRACT
        + "\n\n"
        + _ARTIFACT_INSTRUCTIONS["2D"]
    ),
    "MIXED_3D": (
        "Produce both at least one native structured UI block and exactly one complete 3D "
        "chatcore-artifact block. "
        + STRUCTURED_UI_EXECUTION_CONTRACT
        + "\n\n"
        + _ARTIFACT_INSTRUCTIONS["3D"]
    ),
}
_INJECTABLE_MODES = frozenset(_MODE_INSTRUCTIONS)
_UNDECIDED_MODE_INSTRUCTION = (
    "The pre-answer Generative UI classification was unresolved, so no presentation mode is set. "
    "Choose the mode from the user's request while following the execution contract: use STRUCTURED_UI "
    "when a native comparison, calculation, explanation, or requested diagram materially helps; use "
    "2D or 3D Artifact only for a requested free-form canvas or spatial model; use NONE for brief "
    "answers, ordinary code examples, and explicit text-only requests. Preserve an explicit request "
    "for a visual instead of silently answering only in prose. The chatcore-ui schema and safety "
    "rules in the execution contract apply if you choose STRUCTURED_UI."
    "\n\n"
    + STRUCTURED_UI_EXECUTION_CONTRACT
)

# 「操作・状態変化を求める」依頼だけを拾う。UIモード自体（平面/立体/無し）は
# 「表示してほしい」全般で選ばれるため、可視化そのものの依頼と、それを操作できる
# ことまで求める依頼は別の軸として扱う。操作語を伴わない依頼では静的な結果が
# 正しい姿であり、ここに一致しない。
# Matches only requests that ask to operate or change state, not merely to view something.
# The UI mode decision fires for any "show me" request, so a request to visualize is kept on
# a separate axis from one that also asks for it to be operable. A request with no operation
# wording is correctly static and does not match here.
_JA_INTERACTIVE_OPERATION = (
    r"操作(?:できる|可能)|動かせる|いじれる|"
    r"(?:操作して|調整して|触って)[^。\n]{0,20}(?:できる|られる|めるように|変わ|切り替わ)|"
    r"(?:条件|前提|金利|利率|数値|パラメータ)[^。\n]{0,16}(?:調整|変更|変え|変えた)[^。\n]{0,30}(?:差|結果|返済額|比較|推移|変化|確認|見られる|分かる)|"
    r"再生(?:できる|可能|して)|一時停止|巻き戻し|早送り|"
    r"スライダー(?:で|を)|ドラッグ(?:で|して)|つまみ(?:で|を)|"
    r"ボタン(?:を押すと|を押して|で(?:切り替|操作|選|再生|変更))|押すと(?:変わ|切り替わ)|"
    r"選ぶと(?:変わ|切り替わ)|変更すると(?:変わ|切り替わ)|調整(?:できる|可能)"
)
_EN_INTERACTIVE_OPERATION = (
    r"\binteractive\b|\b(?:adjustable|draggable|playable|clickable|toggleable)\b|"
    r"\bwhat[- ]if\b|\b(?:adjust|change)\b[^.\n]{0,24}\b(?:assumptions?|parameters?|rates?)\b|"
    r"\b(?:drag|slide|toggle|press|click)\b[^.\n]{0,20}\bto\b[^.\n]{0,20}"
    r"\b(?:change|update|adjust|control|reveal)\b|"
    r"\bplay(?:\s*/\s*pause|back)?\b[^.\n]{0,20}\b(?:button|control)\b"
)
_INTERACTIVE_OPERATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"インタラクティブ"),
    re.compile(_JA_INTERACTIVE_OPERATION),
    re.compile(_EN_INTERACTIVE_OPERATION, re.IGNORECASE),
)


def requests_interactive_operation(text: Any) -> bool:
    """Return whether the request itself asks to operate the UI, not merely view it.

    可視化の要求（UIモード判定）とは別の軸の判定。操作語を伴わない依頼では
    静的な結果が正しい姿であり、False を返す。
    A separate axis from the mode decision. A request with no operation wording is correctly
    static, and this returns False for it.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    normalized = text.strip()
    return any(pattern.search(normalized) for pattern in _INTERACTIVE_OPERATION_PATTERNS)


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

    元のリストとメッセージ辞書は変更しない。NONE・不明なモードでは複製だけを返す。
    Neither the list nor its message dicts are mutated. NONE and unknown modes return a copy.
    """
    messages = [dict(message) for message in conversation_messages or []]
    normalized_mode = str(mode or "").strip().upper()
    if mode is None:
        return insert_before_latest_user_message(
            messages,
            {"role": "system", "content": _UNDECIDED_MODE_INSTRUCTION},
        )
    if normalized_mode not in _INJECTABLE_MODES:
        return messages
    if normalized_mode == "STRUCTURED_UI":
        from services.user_skills import GENERATIVE_UI_EXECUTION_CONTRACT

        messages = [
            message
            for message in messages
            if not (
                message.get("role") == "system"
                and message.get("content") == GENERATIVE_UI_EXECUTION_CONTRACT
            )
        ]
    return insert_before_latest_user_message(
        messages,
        {
            "role": "system",
            "content": (
                f"Generated UI mode for this turn is already decided: {normalized_mode}. "
                "The decision is final; do not re-evaluate it. "
                + _MODE_INSTRUCTIONS[normalized_mode]
            ),
        }
    )
