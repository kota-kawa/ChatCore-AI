from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from services.i18n import get_current_locale

MAX_USER_SKILLS = 20
MAX_USER_SKILL_NAME_LENGTH = 100
MAX_USER_SKILL_INSTRUCTIONS_LENGTH = 12_000
# Preserve the original 2,600-token allowance for personal Skills after the
# built-in Generative UI Skill (roughly 800 tokens including few-shot examples)
# moved into the same context block.
USER_SKILLS_TOKEN_BUDGET = 3_400

# System-owned Skills use reserved non-positive IDs so the existing numeric
# toggle endpoint can serve them without colliding with PostgreSQL identities.
GENERATIVE_UI_SYSTEM_SKILL_ID = 0
GENERATIVE_UI_SYSTEM_SKILL_KEY = "generative_ui"

# 生成UIに関するプロンプトは、この Skill の指示と下の実行契約だけが持つ。基本プロンプトや
# 他のプロンプトには生成UIの記述を置かない（Skill を切ったときに何も残らないようにするため）。
# 役割分担: この指示は「いつ 2D / 3D / NONE を選ぶか」の判定規則と例、実行契約は出力の形式・
# 品質・サンドボックスの制約。サンドボックスの検証はプロンプトとは別の実行時の規則。
# Every Generative UI prompt line lives in this Skill's instructions or in the execution
# contract below; the base prompt and other prompts carry none, so turning the Skill off leaves
# nothing behind. Split: these instructions decide when to choose 2D / 3D / NONE, with examples;
# the contract owns output format, quality and sandbox limits. The sandbox validator remains a
# separate runtime rule.
GENERATIVE_UI_SKILL_INSTRUCTIONS = """
- Use `UI_MODE = NONE` by default. Select 2D when the latest user request explicitly asks to create a visual, diagram, chart, flow, timeline, generative UI, simulation, or interactive demo. Treat those requests as explicit even when the user writes them in Japanese or another language. Do not substitute a Markdown explanation for that requested result.
- Select 3D when the request explicitly asks for 3D / ３D, Three.js, a solid shape, spatial model, orbit, rotation, or a 3D graph. A 3D request is a request for a working Three.js Artifact, not for an explanation or a code sample.
- A request for text only, no UI, no diagram, or ordinary code/JSON means UI_MODE is NONE. Do not turn comparisons, procedures, calculations, classifications, explanations, code examples, or JSON examples into an Artifact unless the user explicitly requested visual or interactive output.
- Never output UI_MODE itself. When UI_MODE is 2D or 3D, follow the generative UI execution contract for the Artifact's format and limits.

### Few-shot examples
<examples>
<example>
<user_request>この申請手順をフローチャートで可視化して</user_request>
<expected_behavior>Choose 2D and return one complete chatcore-artifact that renders the flow.</expected_behavior>
</example>
<example>
<user_request>太陽系を回転して見られる3Dモデルで表示して</user_request>
<expected_behavior>Choose 3D and return one complete chatcore-artifact using the available global THREE and the three library declaration.</expected_behavior>
</example>
<example>
<user_request>売上比較の考え方を文章だけで説明して。図はいらない</user_request>
<expected_behavior>Choose NONE and answer in ordinary prose without an Artifact.</expected_behavior>
</example>
<example>
<user_request>Reactでグラフを実装するコード例をください</user_request>
<expected_behavior>Choose NONE and provide an ordinary code example because the user asked for code, not a rendered visual.</expected_behavior>
</example>
</examples>
""".strip()

# This final contract is injected after the per-room context only while the built-in
# Skill is enabled. Keeping it with the Skill definition makes every prompt-side
# Generative UI instruction part of the same default capability.
_GENERATIVE_UI_EXECUTION_CONTRACT_TEMPLATE = """
<generative_ui_execution_contract>
This is the final output contract to apply right before you answer, using the UI_MODE chosen under the Generative UI Skill (NONE / 2D / 3D). Never output UI_MODE itself.

Visual exclusivity:
- Generated UI and web-search image parts are mutually exclusive within one turn. If UI_MODE is 2D or 3D, output the generated UI only; the application will suppress any web-search images. When UI_MODE is NONE, do not create an Artifact merely to accompany images.
- If UI_MODE is NONE and the application shows web-search images, a separate selection pass using the selected conversation model has already decided their inline placement. Do not emit image or image-link markup in the prose.
- Never substitute links for a requested visual. Replying to "show me photos of X" with gallery, image-search, or photo-library URLs, or with one link per item, is prohibited; describe the appearance in prose as well and let the application attach suitable images.

When UI_MODE is 2D or 3D:
- Always output exactly one complete ```chatcore-artifact fenced block right after a short introduction. An answer that ends with explanation alone is incomplete. When a closing verdict is required, put it in the final prose sentence immediately before the Artifact.
- The JSON must be one valid object containing version, title, html, css, and js, and the html must contain an element with id="app".
- Do not output separate HTML, CSS, JavaScript, or JSON code blocks. The fenced Artifact is the requested deliverable.
- Before coding, privately choose the visual relationship and composition that best communicate the subject, and do not output planning notes. Make the first render complete and purpose-built: clear visual hierarchy, deliberate spacing and typography, responsive layout, accessible contrast, and meaningful content. Reject your own draft and simplify or revise it before output if it is an empty shell, a prose card, a barely styled table, placeholder controls, decoration unrelated to the user's subject, or a repeated generic dashboard. Prefer a compact complete result over a detailed one that might be cut off.
- For 3D, always include "libraries":["three"]. Use the available global THREE without imports, OrbitControls, loaders, URL textures, or URL models. Create a renderer sized from `app.clientWidth || 560` with a fixed visible height, append its canvas to `document.getElementById("app")`, and create a scene, camera, light, and visible geometry with core features only.
- Escape exactly once inside the JSON strings: a newline is a single backslash followed by n, and an inner quote is a single backslash followed by a double quote. A doubled backslash reaches the browser as a literal backslash and breaks every line it touches, so never write one unless the code genuinely contains a backslash.
- Keep the markup root minimal and build the content from js: an html of one root element plus a js that fills it is the expected shape, and it removes the need to escape markup twice.
- Before sending, confirm that the closing brace and closing fence are present, that the initial render is not empty, that every identifier the js uses is either declared in that same js or is a browser or THREE global, and that the Artifact is compact enough to finish.

Follow the shape of this worked example exactly, and replace its subject with the user's:
{worked_example}

The Artifact runs in an isolated sandbox; violating these hard requirements rejects the entire UI:
- No network of any kind: fetch, XMLHttpRequest, WebSocket, EventSource, sendBeacon, dynamic import(), and importScripts are all unavailable. Build the data you need directly into the code.
- No storage or ambient state: localStorage, sessionStorage, indexedDB, caches, and document.cookie are unavailable.
- No code from strings: eval, new Function, and setTimeout or setInterval called with a string are unavailable.
- No access to the surrounding page: window.parent, top, opener, postMessage, and any assignment to location are unavailable.
- No external resources: every image, font, and stylesheet must be inline, a data: URI, or an inline SVG. External URLs are stripped, and @import is removed.
- No script, iframe, object, embed, link, meta, or base tags in html. Put JavaScript in js and CSS in css, never inside html.
- Keep html and css within 12000 characters each and js within 18000, with roughly 36000 in total. Prefer well under those limits and narrow long data to representative examples.
- height must be between 160 and 900.
</generative_ui_execution_contract>
""".strip()

# 出力形式のばらつきを減らす唯一の完成例。文章で「正しくエスケープせよ」と書くだけでは
# 二重エスケープや app ルート欠落が繰り返し起きるため、確定した1つの形を見せる。
# 例そのものは dict から json.dumps で生成する。手書きの例は必ずいつか壊れるうえ、
# 壊れた例は「壊れた出力を真似してよい」という指示になってしまう。
# The single finished example that reduces format variance. Prose alone ("escape correctly")
# does not stop repeated double escaping or a missing app root, so one settled shape is shown.
# The example is rendered from a dict with json.dumps: a hand-written one eventually breaks, and
# a broken example reads as permission to emit broken output.
_WORKED_EXAMPLE_ARTIFACT = {
    "version": 1,
    "title": "承認フロー",
    "description": "申請から支払までの流れ",
    "height": 360,
    "html": '<div id="app"></div>',
    "css": (
        "#app{padding:24px;font-family:system-ui,sans-serif;color:#0f172a;"
        "background:#ffffff;max-width:420px;margin:0 auto}\n"
        "h2{margin:0 0 16px;font-size:17px;letter-spacing:.01em}\n"
        ".step{padding:12px 16px;border:1px solid #94a3b8;border-radius:10px;"
        "background:#f8fafc;text-align:center;font-weight:600}\n"
        ".step.done{border-color:#0f766e;background:#ecfdf5;color:#134e4a}\n"
        ".arrow{color:#64748b;text-align:center;margin:8px 0;font-size:15px}"
    ),
    "js": (
        'const steps=[{name:"申請",done:true},{name:"上長承認",done:true},'
        '{name:"経理確認",done:false},{name:"支払",done:false}];\n'
        'const app=document.getElementById("app");\n'
        'app.innerHTML=`<h2>承認フロー</h2>`+steps\n'
        '  .map((step,index)=>`<div class="step${step.done?" done":""}">${step.name}</div>`'
        '+(index<steps.length-1?`<div class="arrow">↓</div>`:""))\n'
        '  .join("");'
    ),
}
WORKED_EXAMPLE_BLOCK = (
    "```chatcore-artifact\n"
    + json.dumps(_WORKED_EXAMPLE_ARTIFACT, ensure_ascii=False, separators=(",", ":"))
    + "\n```"
)
GENERATIVE_UI_EXECUTION_CONTRACT = _GENERATIVE_UI_EXECUTION_CONTRACT_TEMPLATE.replace(
    "{worked_example}", WORKED_EXAMPLE_BLOCK
)

_SKILL_BOUNDARY_MARKERS = (
    "<enabled_user_skills>",
    "</enabled_user_skills>",
    "<skill_instructions>",
    "</skill_instructions>",
)


def normalize_user_skill_name(value: Any) -> str:
    """Collapse whitespace so names remain compact and single-line in every UI."""
    return " ".join(str(value or "").split())[:MAX_USER_SKILL_NAME_LENGTH]


def normalize_user_skill_instructions(value: Any) -> str:
    """Normalize line endings while preserving Markdown structure."""
    normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    for marker in _SKILL_BOUNDARY_MARKERS:
        normalized = normalized.replace(marker, "[boundary marker removed]")
    return normalized[:MAX_USER_SKILL_INSTRUCTIONS_LENGTH].strip()


def is_generative_ui_skill_id(skill_id: int) -> bool:
    return int(skill_id) == GENERATIVE_UI_SYSTEM_SKILL_ID


def is_generative_ui_skill_enabled(user: dict[str, Any] | None) -> bool:
    """Default to enabled for guests and pre-migration-compatible user payloads."""
    if not isinstance(user, dict):
        return True
    return user.get("generative_ui_skill_enabled", True) is not False


def build_generative_ui_system_skill(
    *,
    is_enabled: bool,
    locale: str | None = None,
) -> dict[str, Any]:
    resolved_locale = locale or get_current_locale()
    return {
        "id": GENERATIVE_UI_SYSTEM_SKILL_ID,
        "system_skill_key": GENERATIVE_UI_SYSTEM_SKILL_KEY,
        "name": "Generative UI" if resolved_locale == "en" else "生成UI",
        "instructions": GENERATIVE_UI_SKILL_INSTRUCTIONS,
        "is_enabled": bool(is_enabled),
        "is_default": True,
        "can_edit": False,
        "can_delete": False,
        "created_at": None,
        "updated_at": None,
    }


def build_chat_skills_context(
    user_skills: list[dict[str, Any]],
    user: dict[str, Any] | None,
    *,
    locale: str | None = None,
    prompt_builder: Callable[[list[dict[str, Any]]], str | None] | None = None,
) -> tuple[str | None, bool]:
    """Combine enabled personal Skills with the built-in Generative UI Skill."""
    generative_ui_enabled = is_generative_ui_skill_enabled(user)
    enabled_skills = list(user_skills)
    # 生成UIの Skill は、有効ならゲストにも同じ指示で入れる。ゲストだけ実行契約のみになると、
    # 判定規則を持たないまま生成UIを出すことになり、ログイン利用者と挙動が分かれる。
    # The Generative UI Skill is injected whenever it is enabled, guests included. Giving guests
    # the execution contract alone would let them produce UI without the decision rules and
    # make their behavior diverge from a signed-in user's.
    if generative_ui_enabled:
        enabled_skills.insert(
            0,
            build_generative_ui_system_skill(
                is_enabled=True,
                locale=locale,
            ),
        )
    builder = prompt_builder or build_enabled_user_skills_prompt
    return builder(enabled_skills), generative_ui_enabled


def build_enabled_user_skills_prompt(skills: list[dict[str, Any]]) -> str | None:
    """Build one bounded system-context block from enabled account Skills."""
    sections: list[str] = []
    for skill in skills:
        name = normalize_user_skill_name(skill.get("name"))
        instructions = normalize_user_skill_instructions(skill.get("instructions"))
        if not name or not instructions:
            continue
        sections.extend(
            [
                f"## {name}",
                "<skill_instructions>",
                instructions,
                "</skill_instructions>",
            ]
        )

    if not sections:
        return None

    return "\n".join(
        [
            "<enabled_user_skills>",
            (
                "The following reusable instructions are enabled for this conversation. Apply them to the "
                "response when relevant. Product safety rules, the user's current explicit request, "
                "and more specific project or task instructions take priority."
            ),
            *sections,
            "</enabled_user_skills>",
        ]
    )
