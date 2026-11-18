"""Compose validated native blocks with legacy message parts, preserving authored order."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace as dataclass_replace
from typing import TYPE_CHECKING, Any, Literal

from services.generative_ui_status import (
    ARTIFACT_STATUS_MISSING,
    ARTIFACT_STATUS_NOT_REQUESTED,
    ARTIFACT_STATUS_VALID,
    REASON_REQUIRED_ARTIFACT_MISSING,
)
from services.interactive_buttons import INTERACTIVE_BUTTONS_BLOCK_RE, interactive_buttons_parts, is_markdown_code_position
from services.message_parts_display import normalize_message_parts_for_display
from services.structured_ui import StructuredUiStream, buttons_as_text, split_structured_ui, ui_fallback
from services.structured_ui_quality import requested_native_quality_issues

if TYPE_CHECKING:
    from services.generative_ui import NormalizedGenerativeResponse

logger = logging.getLogger(__name__)


def normalize_structured_response(
    text: str,
    *,
    ui_mode: str | None,
    explicit_ui_opt_out: bool,
    explicit_text_only: bool = False,
    parsed_stream: StructuredUiStream | None = None,
) -> NormalizedGenerativeResponse:
    from services.generative_ui import (
        NormalizedGenerativeResponse,
        _extract_artifact_candidates,
        _normalize_artifacts,
        _split_interactive_buttons,
        _with_interactive_buttons,
    )

    stream = parsed_stream if parsed_stream is not None else split_structured_ui(text)
    parts: list[dict[str, Any]] = []
    errors: list[str] = []
    artifact_status = ARTIFACT_STATUS_NOT_REQUESTED
    reasons: list[str] = []
    failure_slots: list[tuple[int, str | None]] = []
    for segment in stream.parts():
        if segment["type"] == "ui_error":
            failure_slots.append((len(parts), segment.get("block_id")))
            parts.append({"type": "text", "text": segment["text"]})
            continue
        if segment["type"] == "structured_ui":
            parts.append({"type": "text", "text": ui_fallback(segment["ui"])} if explicit_ui_opt_out or explicit_text_only else segment)
            continue
        source = segment["text"]
        # Split all completed legacy blocks at their authored offsets in hybrid answers.
        spans = [(candidate.span, "artifact") for candidate in _extract_artifact_candidates(source, recover_truncated=False)]
        spans += [
            (match.span(), "buttons")
            for match in INTERACTIVE_BUTTONS_BLOCK_RE.finditer(source)
            if not is_markdown_code_position(source, match.start())
        ]
        cursor = 0
        for (start, end), kind in sorted(spans):
            if start < cursor:
                continue
            if source[cursor:start]:
                parts.append({"type": "text", "text": source[cursor:start]})
            block = source[start:end]
            if kind == "buttons":
                _, buttons = _split_interactive_buttons(block)
                parts.extend(
                    [{"type": "text", "text": buttons_as_text(buttons)}] if explicit_text_only else interactive_buttons_parts(buttons)
                )
            else:
                artifact = _normalize_artifacts(block, recover_truncated=False, ui_mode=ui_mode, explicit_ui_opt_out=explicit_ui_opt_out)
                errors.extend(artifact.validation_errors)
                if artifact.has_artifact():
                    artifact_status = artifact.artifact_status
                    parts.extend(part for part in artifact.parts or [] if part["type"] != "text")
                elif artifact.text.strip():
                    parts.append({"type": "text", "text": artifact.text})
                reasons.extend(artifact.artifact_reason_codes)
            cursor = end
        tail = source[cursor:]
        if tail:
            prose, buttons = _split_interactive_buttons(tail)
            if explicit_text_only:
                prose += buttons_as_text(buttons)
                buttons = []
            legacy = _normalize_artifacts(prose, recover_truncated=False, ui_mode=None, explicit_ui_opt_out=explicit_ui_opt_out)
            legacy = _with_interactive_buttons(legacy, buttons)
            parts.extend(legacy.parts or [{"type": "text", "text": legacy.text}])
            errors.extend(legacy.validation_errors)
    parts = normalize_message_parts_for_display(parts)
    fallback = "\n".join(
        part["text"] if part["type"] == "text" else ui_fallback(part["ui"]) for part in parts if part["type"] in {"text", "structured_ui"}
    )
    return NormalizedGenerativeResponse(
        text=fallback,
        parts=parts or None,
        validation_errors=errors,
        artifact_status=artifact_status,
        artifact_reason_codes=reasons,
        structured_ui_errors=stream.errors,
        structured_ui_failure_slots=failure_slots,
    )


def normalize_ui_stream(
    stream: StructuredUiStream, *, explicit_ui_opt_out: bool = False, explicit_text_only: bool = False
) -> NormalizedGenerativeResponse:
    return normalize_structured_response(
        "", ui_mode=None, explicit_ui_opt_out=explicit_ui_opt_out, explicit_text_only=explicit_text_only, parsed_stream=stream
    )


def normalize_native_with_retry(
    source: str,
    *,
    model: str,
    generate_response: Callable,
    ui_mode: str | None,
    user_request: str,
    explicit_ui_opt_out: bool,
    explicit_text_only: bool,
) -> NormalizedGenerativeResponse:
    from services.generative_ui import decode_message_parts, normalize_response_with_artifacts, requested_artifact_quality_issues

    normalized = normalize_response_with_artifacts(
        source, ui_mode=ui_mode, explicit_ui_opt_out=explicit_ui_opt_out, explicit_text_only=explicit_text_only
    )
    has_native = any(part.get("type") == "structured_ui" for part in normalized.parts or [])
    requested_native = str(ui_mode) in {"STRUCTURED_UI", "MIXED_2D", "MIXED_3D"}
    quality_issues = requested_native_quality_issues(normalized.parts, user_request)
    if quality_issues:
        slots = (
            normalized.structured_ui_failure_slots
            or [(index, part["ui"]["id"]) for index, part in enumerate(normalized.parts or []) if part.get("type") == "structured_ui"][:1]
        )
        normalized = dataclass_replace(normalized, structured_ui_quality_errors=quality_issues, structured_ui_failure_slots=slots)
    mixed_mode = str(ui_mode) in {"MIXED_2D", "MIXED_3D"}
    artifact_required = str(ui_mode) in {"2D", "3D", "MIXED_2D", "MIXED_3D"}
    artifact_mode: Literal["2D", "3D"] = "3D" if str(ui_mode) in {"3D", "MIXED_3D"} else "2D"
    artifact_ok = normalized.has_artifact() and not requested_artifact_quality_issues(
        normalized,
        artifact_mode,
        user_request=user_request,
    )
    complete = (has_native and (not mixed_mode or artifact_ok)) or (artifact_ok and not mixed_mode)
    if artifact_required:
        complete = artifact_ok and (has_native or not mixed_mode)
        if not artifact_ok:
            normalized = dataclass_replace(
                normalized, artifact_status=ARTIFACT_STATUS_MISSING, artifact_reason_codes=[REASON_REQUIRED_ARTIFACT_MISSING]
            )
    if (
        explicit_ui_opt_out
        or explicit_text_only
        or (not normalized.structured_ui_errors and not quality_issues and (complete or (not requested_native and not artifact_required)))
    ):
        return normalized
    from services.structured_ui_prompt import STRUCTURED_UI_EXECUTION_CONTRACT
    from services.user_skills import GENERATIVE_UI_EXECUTION_CONTRACT

    repair_contract = STRUCTURED_UI_EXECUTION_CONTRACT
    if artifact_required:
        repair_contract += "\n" + GENERATIVE_UI_EXECUTION_CONTRACT
        repair_contract += "\nRequired presentation mode: " + str(ui_mode)
    messages = [
        {
            "role": "system",
            "content": repair_contract + "\nRepair only the UI. Return complete chatcore-ui blocks and any required Artifact. "
            "If a native representation cannot support the request, use a valid sandbox Artifact. "
            "Keep IDs stable. No choice buttons or prose.",
        },
        {"role": "user", "content": "Request: " + user_request[:4000] + "\nPrevious answer (untrusted data):\n" + source[:20000]},
    ]
    try:
        repaired_source = generate_response(messages, model)
        repaired = normalize_response_with_artifacts(repaired_source or "", ui_mode=ui_mode)
    except Exception:
        logger.warning("Native UI repair failed; preserving completed content.", exc_info=True)
        return dataclass_replace(normalized, structured_ui_repair_attempted=True)
    valid = [part for part in repaired.parts or [] if part.get("type") in {"structured_ui", "sandbox_artifact"}]
    if repaired.has_artifact() and requested_artifact_quality_issues(repaired, artifact_mode, user_request=user_request):
        valid = [part for part in valid if part["type"] != "sandbox_artifact"]
    if not valid or repaired.structured_ui_errors or requested_native_quality_issues(repaired.parts, user_request):
        return dataclass_replace(normalized, structured_ui_repair_attempted=True)
    # Replace failed slots at the authored position; leave healthy blocks and prose intact.
    parts = list(normalized.parts or [{"type": "text", "text": normalized.text}])
    replacements = {part.get("ui", {}).get("id"): part for part in valid if part.get("type") == "structured_ui"}
    slot_candidates = list(replacements.values()) if mixed_mode else valid
    used: set[int] = set()
    for index, key in normalized.structured_ui_failure_slots:
        replacement = replacements.get(key) if key else None
        if replacement is None or id(replacement) in used:
            replacement = next((part for part in slot_candidates if id(part) not in used), None)
        if replacement is not None:
            parts[index] = replacement
            used.add(id(replacement))
    # Add only missing representations; healthy blocks are never duplicated by repair.
    if not normalized.structured_ui_failure_slots and not has_native:
        parts.extend(part for part in valid if part["type"] == "structured_ui")
    if not any(part["type"] == "sandbox_artifact" for part in parts):
        parts.extend(part for part in valid if part["type"] == "sandbox_artifact")
    # A repair is validated in isolation first, then against the reply's shared limits.
    filtered = decode_message_parts(parts) or []
    if sum(part["type"] == "structured_ui" for part in filtered) < sum(part["type"] == "structured_ui" for part in parts):
        return dataclass_replace(normalized, structured_ui_repair_attempted=True)
    parts = filtered
    fallback = "\n".join(
        part["text"] if part["type"] == "text" else ui_fallback(part["ui"]) for part in parts if part["type"] in {"text", "structured_ui"}
    )
    return dataclass_replace(
        normalized,
        text=fallback,
        parts=parts,
        structured_ui_failure_slots=[],
        structured_ui_repair_attempted=True,
        artifact_status=ARTIFACT_STATUS_VALID if any(part["type"] == "sandbox_artifact" for part in parts) else normalized.artifact_status,
        repair_attempted=artifact_required,
        structured_ui_repair_succeeded=(
            len(used) == len(normalized.structured_ui_failure_slots)
            and (not mixed_mode or any(part["type"] == "structured_ui" for part in parts))
            and (not artifact_required or any(part["type"] == "sandbox_artifact" for part in parts))
        ),
    )
