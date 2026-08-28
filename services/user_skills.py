from __future__ import annotations

from typing import Any


MAX_USER_SKILLS = 20
MAX_USER_SKILL_NAME_LENGTH = 100
MAX_USER_SKILL_INSTRUCTIONS_LENGTH = 12_000
USER_SKILLS_TOKEN_BUDGET = 2_600

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


def build_enabled_user_skills_prompt(skills: list[dict[str, Any]]) -> str | None:
    """Build one bounded system-context block from enabled, user-owned skills."""
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
                "The account owner enabled the following reusable instructions. Apply them to the "
                "response when relevant. Product safety rules, the user's current explicit request, "
                "and more specific project or task instructions take priority."
            ),
            *sections,
            "</enabled_user_skills>",
        ]
    )
