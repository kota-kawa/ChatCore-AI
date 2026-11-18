#!/usr/bin/env python3
"""Compare baseline and current answer prompts on fixed Issue 870 cases.

Dry-run by default. ``--execute`` makes ten serial model calls after preflight.
The already-recorded Skill-selection decisions are loaded from
``--classification-report`` so this comparison does not reclassify requests.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Protocol, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if TYPE_CHECKING:
    from services.repositories.usage_repository import UsageIncrement

DATASET_PATH = ROOT / "tests/fixtures/llm_eval/generative_ui_mode_selection_cases_v1.json"
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_CALLS = 10
MAX_INPUT_TOKENS_PER_CALL = 8_000
MAX_OUTPUT_TOKENS_PER_CALL = 8_192
AFTER_SOURCE_PATHS = (
    "services/chat_prompt.py",
    "services/chat_skill_selection.py",
    "services/generative_ui_intent.py",
    "services/structured_ui_prompt.py",
    "services/user_skills.py",
)


class OutputTokenLimit(Protocol):
    def __call__(self, model_name: str | None, generation_phase: str = "default") -> int: ...


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Call the configured model; default is dry-run.")
    parser.add_argument("--classification-report", type=Path, required=True)
    parser.add_argument("--baseline-ref", default="origin/main")
    parser.add_argument("--messages-output", type=Path, help="Write the exact baseline/after prompts to this JSON file.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--input-cap-tokens", type=int, default=MAX_INPUT_TOKENS_PER_CALL)
    parser.add_argument("--output-cap-tokens", type=int, default=MAX_OUTPUT_TOKENS_PER_CALL)
    parser.add_argument("--max-estimated-usd", type=Decimal, default=Decimal("0.10"))
    return parser.parse_args()


def _git_source(relative_path: str, baseline_ref: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{baseline_ref}:{relative_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _commit_hash(baseline_ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{baseline_ref}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _source_fingerprint(paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative_path in paths:
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update((ROOT / relative_path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}.")
    return payload, hashlib.sha256(raw).hexdigest()


def _classification_decisions(report: dict[str, Any], case_ids: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    calls = report.get("calls")
    if not isinstance(calls, list):
        raise TypeError("Classification report must contain a 'calls' array.")
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for item in calls:
        if not isinstance(item, dict):
            continue
        case_id = item.get("case_id")
        variant = item.get("variant")
        if case_id not in case_ids or variant not in {"baseline", "after"}:
            continue
        key = (str(case_id), str(variant))
        repeat = item.get("repeat", 1)
        previous = selected.get(key)
        if previous is None or int(repeat) < int(previous.get("repeat", 1)):
            selected[key] = item
    expected = {(case_id, variant) for case_id in case_ids for variant in ("baseline", "after")}
    missing = expected - set(selected)
    if missing:
        labels = ", ".join(f"{case}/{variant}" for case, variant in sorted(missing))
        raise ValueError(f"Classification report lacks decisions for: {labels}.")
    return selected


def _exec_module(name: str, source: str) -> ModuleType:
    module = ModuleType(name)
    module.__package__ = "services"
    sys.modules[name] = module
    exec(compile(source, name, "exec"), module.__dict__)
    return module


def _load_baseline_modules(baseline_ref: str) -> tuple[ModuleType, ModuleType, ModuleType]:
    return (
        _exec_module("services._issue870_response_baseline_user_skills", _git_source("services/user_skills.py", baseline_ref)),
        _exec_module("services._issue870_response_baseline_chat_prompt", _git_source("services/chat_prompt.py", baseline_ref)),
        _exec_module(
            "services._issue870_response_baseline_generative_ui_intent",
            _git_source("services/generative_ui_intent.py", baseline_ref),
        ),
    )


def _selected_context(skills_module: ModuleType, selection: dict[str, Any]) -> Any:
    context = skills_module.build_chat_skills_context(
        [],
        {
            "id": 870,
            "generative_ui_skill_enabled": True,
            "memo_tools_skill_enabled": False,
            "prompt_tools_skill_enabled": False,
        },
        locale="ja",
        workspace_tools_available=True,
    )
    selected_ids_raw = selection.get("selected_skill_ids", [])
    if not isinstance(selected_ids_raw, list) or not all(type(value) is int for value in selected_ids_raw):
        raise ValueError("Classification report contains invalid selected_skill_ids.")
    selected_ids = set(selected_ids_raw)
    selected_records = [skill for skill_id, skill in context._prompt_skills_by_id if skill_id in selected_ids]
    builder = context._prompt_builder or skills_module.build_enabled_user_skills_prompt
    return replace(
        context,
        prompt=builder(selected_records),
        generative_ui_selected=0 in selected_ids,
        memo_tools_enabled=False,
        prompt_tools_enabled=False,
    )


def _latest_user_message(messages: list[dict[str, Any]]) -> str:
    return next((str(message.get("content", "")) for message in reversed(messages) if message.get("role") == "user"), "")


def _build_generation_messages(
    case: dict[str, Any],
    selection: dict[str, Any],
    *,
    skills_module: Any,
    chat_prompt_module: Any,
    intent_module: Any,
    chat_context_module: Any,
    fixed_now: datetime,
) -> list[dict[str, str]]:
    context = _selected_context(skills_module, selection)
    ui_mode = selection.get("ui_mode")
    recent_messages = cast(list[dict[str, str]], case["messages"])
    saved_contract = chat_context_module.GENERATIVE_UI_EXECUTION_CONTRACT
    saved_runtime_builder = chat_context_module.build_runtime_context_message
    saved_insert_before_latest_user = chat_context_module.insert_before_latest_user_message
    try:
        chat_context_module.GENERATIVE_UI_EXECUTION_CONTRACT = skills_module.GENERATIVE_UI_EXECUTION_CONTRACT
        chat_context_module.build_runtime_context_message = partial(
            chat_prompt_module.build_runtime_context_message, current_time=fixed_now
        )
        chat_context_module.insert_before_latest_user_message = chat_prompt_module.insert_before_latest_user_message
        messages = cast(
            list[dict[str, str]],
            chat_context_module.build_context_messages(
                base_system_prompt=chat_prompt_module.build_base_system_prompt(locale="ja"),
                user_profile_prompt=None,
                task_prompt=None,
                room_summary="",
                memory_facts=[],
                recent_messages=recent_messages,
                project_instructions=None,
                user_skills_prompt=context.prompt,
                generative_ui_enabled=context.generative_ui_selected,
            ),
        )
    finally:
        chat_context_module.GENERATIVE_UI_EXECUTION_CONTRACT = saved_contract
        chat_context_module.build_runtime_context_message = saved_runtime_builder
        chat_context_module.insert_before_latest_user_message = saved_insert_before_latest_user

    latest_user = _latest_user_message(recent_messages)
    explicit_ui_opt_out = intent_module.is_explicit_generative_ui_opt_out(latest_user)
    if not explicit_ui_opt_out:
        messages = intent_module.inject_generative_ui_mode_instruction(messages, ui_mode)
    return messages


def _plan(
    cases: list[dict[str, Any]],
    decisions: dict[tuple[str, str], dict[str, Any]],
    modules: dict[str, Any],
    fixed_now: datetime,
    model: str,
    input_cap_tokens: int,
    output_cap_tokens: int,
    messages_output: Path | None,
    classification_report_sha256: str,
    baseline_ref: str,
) -> tuple[list[dict[str, Any]], str | None]:
    from services.llm_context_budget import estimate_messages_tokens
    from services.usage_pricing import token_cost_nano_usd

    plan: list[dict[str, Any]] = []
    message_artifacts: list[dict[str, Any]] = []
    chat_context_module = importlib.import_module("services.chat_context")
    for case in cases:
        for variant in ("baseline", "after"):
            prefix = "baseline" if variant == "baseline" else "current"
            messages = _build_generation_messages(
                case,
                decisions[(case["id"], variant)],
                skills_module=modules[f"{prefix}_skills"],
                chat_prompt_module=modules[f"{prefix}_prompt"],
                intent_module=modules[f"{prefix}_intent"],
                chat_context_module=chat_context_module,
                fixed_now=fixed_now,
            )
            input_tokens = estimate_messages_tokens(messages)
            if input_tokens > input_cap_tokens:
                raise ValueError(f"{case['id']} {variant} input estimate {input_tokens} exceeds the {input_cap_tokens}-token cap.")
            message_artifacts.append(
                {
                    "case_id": case["id"],
                    "variant": variant,
                    "ui_mode": decisions[(case["id"], variant)].get("ui_mode"),
                    "selected_skill_ids": decisions[(case["id"], variant)].get("selected_skill_ids", []),
                    "messages": messages,
                }
            )
            plan.append(
                {
                    "case_id": case["id"],
                    "variant": variant,
                    "ui_mode": decisions[(case["id"], variant)].get("ui_mode"),
                    "selected_skill_ids": decisions[(case["id"], variant)].get("selected_skill_ids", []),
                    "input_tokens_estimate": input_tokens,
                    "output_tokens_cap": output_cap_tokens,
                    "estimated_cost_nano_usd": token_cost_nano_usd(
                        model,
                        input_tokens=input_tokens,
                        output_tokens=output_cap_tokens,
                    ),
                }
            )
    if len(plan) != MAX_CALLS:
        raise ValueError(f"Expected exactly {MAX_CALLS} planned calls; got {len(plan)}.")
    message_artifact_sha256: str | None = None
    if messages_output is not None:
        artifact = {
            "dataset_id": "generative_ui_mode_selection_v1",
            "dataset_sha256": hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest(),
            "classification_report_sha256": classification_report_sha256,
            "baseline_ref": baseline_ref,
            "baseline_commit_hash": _commit_hash(baseline_ref),
            "after_source_fingerprint": _source_fingerprint(AFTER_SOURCE_PATHS),
            "generation_phase": "agent",
            "tools": None,
            "messages": message_artifacts,
        }
        serialized = json.dumps(artifact, ensure_ascii=False, indent=2)
        messages_output.parent.mkdir(parents=True, exist_ok=True)
        messages_output.write_text(serialized + "\n", encoding="utf-8")
        message_artifact_sha256 = hashlib.sha256((serialized + "\n").encode("utf-8")).hexdigest()
    return plan, message_artifact_sha256


def _usd(nano_usd: int) -> str:
    return f"{Decimal(nano_usd) / Decimal(1_000_000_000):.6f}"


def main() -> int:
    args = _parse_args()
    if not 1 <= args.input_cap_tokens <= MAX_INPUT_TOKENS_PER_CALL:
        raise ValueError(f"--input-cap-tokens must be between 1 and {MAX_INPUT_TOKENS_PER_CALL}.")
    if not 1 <= args.output_cap_tokens <= MAX_OUTPUT_TOKENS_PER_CALL:
        raise ValueError(f"--output-cap-tokens must be between 1 and {MAX_OUTPUT_TOKENS_PER_CALL}.")
    classification_report, classification_sha256 = _load_json(args.classification_report)
    dataset, dataset_sha256 = _load_json(DATASET_PATH)
    cases = dataset.get("cases")
    if not isinstance(cases, list) or len(cases) != 5:
        raise ValueError("The fixed Issue 870 response comparison requires exactly five fixture cases.")
    case_ids = [str(case["id"]) for case in cases]
    if classification_report.get("dataset_id") != dataset.get("dataset_id"):
        raise ValueError("Classification report dataset_id does not match the fixed fixture.")
    if classification_report.get("dataset_sha256") != dataset_sha256:
        raise ValueError("Classification report fixture hash does not match the fixed fixture.")
    report_baseline_hash = classification_report.get("baseline_commit_hash")
    if report_baseline_hash is not None and report_baseline_hash != _commit_hash(args.baseline_ref):
        raise ValueError("Classification report baseline commit does not match --baseline-ref.")
    decisions = _classification_decisions(classification_report, case_ids)

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    if args.execute:
        # The eval process must not retry a paid completion after a transient failure.
        os.environ["LLM_MAX_RETRIES"] = "0"

    current_skills = importlib.import_module("services.user_skills")
    current_prompt = importlib.import_module("services.chat_prompt")
    current_intent = importlib.import_module("services.generative_ui_intent")
    baseline_skills, baseline_prompt, baseline_intent = _load_baseline_modules(args.baseline_ref)
    modules = {
        "baseline_skills": baseline_skills,
        "baseline_prompt": baseline_prompt,
        "baseline_intent": baseline_intent,
        "current_skills": current_skills,
        "current_prompt": current_prompt,
        "current_intent": current_intent,
    }
    llm = importlib.import_module("services.llm")
    llm.validate_model_name(args.model)
    if not llm.is_groq_model(args.model):
        raise ValueError("This script caps output through the Groq response path; choose a supported Groq model.")
    fixed_now = datetime.now().astimezone()
    plan, messages_artifact_sha256 = _plan(
        cases,
        decisions,
        modules,
        fixed_now,
        args.model,
        args.input_cap_tokens,
        args.output_cap_tokens,
        args.messages_output,
        classification_sha256,
        args.baseline_ref,
    )
    estimated_cost = sum(int(item["estimated_cost_nano_usd"]) for item in plan)
    budget_nano_usd = int(args.max_estimated_usd * Decimal(1_000_000_000))
    if estimated_cost > budget_nano_usd:
        raise ValueError(f"Estimated cost ${_usd(estimated_cost)} exceeds --max-estimated-usd ${args.max_estimated_usd}.")

    report: dict[str, Any] = {
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": dataset_sha256,
        "classification_report_sha256": classification_sha256,
        "baseline_ref": args.baseline_ref,
        "baseline_commit_hash": _commit_hash(args.baseline_ref),
        "after_source_fingerprint": _source_fingerprint(AFTER_SOURCE_PATHS),
        "model": args.model,
        "calls_planned": len(plan),
        "input_cap_tokens_per_call": args.input_cap_tokens,
        "output_cap_tokens_per_call": args.output_cap_tokens,
        "estimated_max_cost_usd": _usd(estimated_cost),
        "cases": case_ids,
        "messages_artifact_path": str(args.messages_output.resolve()) if args.messages_output is not None else None,
        "messages_artifact_sha256": messages_artifact_sha256,
        "plan": plan,
        "telemetry_limits": {
            "measured": [
                "elapsed_ms",
                "usage input/output tokens",
                "usage.cost_nano_usd",
                "output characters",
                "JSON validation failures",
                "first_response_chunk_ms (provider content, before server display filtering)",
                "first_pass_finish_reason",
                "normalized parts and required UI part presence",
            ],
            "not_exercised_without_the_agent_loop": ["stream continuation count", "repair calls"],
            "repair_calls": 0,
        },
    }
    if not args.execute:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    from services.usage_metering import set_usage_sink

    usage_records: list[UsageIncrement] = []
    set_usage_sink(usage_records.append)
    generative_ui = importlib.import_module("services.generative_ui")
    from services.structured_ui_quality import requested_native_quality_issues

    ui_intent_current = current_intent
    llm_dynamic = cast(Any, llm)
    output_limit_original = cast(OutputTokenLimit, llm_dynamic.max_output_tokens_for_model)
    output_cap = int(args.output_cap_tokens)

    def capped_output_limit(model_name: str, generation_phase: str = "default") -> int:
        return min(output_limit_original(model_name, generation_phase), output_cap)

    llm_dynamic.max_output_tokens_for_model = capped_output_limit
    outputs: list[dict[str, Any]] = []
    try:
        for case in cases:
            latest_user = _latest_user_message(cast(list[dict[str, Any]], case["messages"]))
            explicit_ui_opt_out = ui_intent_current.is_explicit_generative_ui_opt_out(latest_user)
            explicit_text_only = generative_ui.is_text_only_request(latest_user)
            for variant in ("baseline", "after"):
                decision = decisions[(case["id"], variant)]
                prefix = "baseline" if variant == "baseline" else "current"
                messages = _build_generation_messages(
                    case,
                    decision,
                    skills_module=modules[f"{prefix}_skills"],
                    chat_prompt_module=modules[f"{prefix}_prompt"],
                    intent_module=modules[f"{prefix}_intent"],
                    chat_context_module=importlib.import_module("services.chat_context"),
                    fixed_now=fixed_now,
                )
                call_usage_start = len(usage_records)
                start = time.perf_counter()
                response_chunks: list[str] = []
                first_response_chunk_ms: float | None = None
                first_pass_finish_reason = "stop"
                try:
                    for chunk in llm.get_llm_response_stream(
                        messages,
                        args.model,
                        tools=None,
                        generation_phase="agent",
                    ):
                        if first_response_chunk_ms is None and chunk.strip():
                            first_response_chunk_ms = round((time.perf_counter() - start) * 1000, 2)
                        response_chunks.append(chunk)
                except llm.LlmOutputLimitError as exc:
                    first_pass_finish_reason = exc.reason
                raw_response = "".join(response_chunks)
                elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
                normalized = generative_ui.normalize_response_with_artifacts(
                    raw_response or "",
                    ui_mode=decision.get("ui_mode"),
                    explicit_ui_opt_out=explicit_ui_opt_out,
                    explicit_text_only=explicit_text_only,
                )
                parts = normalized.parts or []
                native_count = sum(part.get("type") == "structured_ui" for part in parts)
                artifact_count = sum(part.get("type") == "sandbox_artifact" for part in parts)
                mode = decision.get("ui_mode")
                native_required = mode in {"STRUCTURED_UI", "MIXED_2D", "MIXED_3D"}
                artifact_required = mode in {"2D", "3D", "MIXED_2D", "MIXED_3D"}
                required_parts_present = (not native_required or native_count > 0) and (not artifact_required or artifact_count > 0)
                mode_contract_satisfied = (
                    None
                    if mode is None
                    else (required_parts_present and (native_required or native_count == 0) and (artifact_required or artifact_count == 0))
                )
                validation_failed = bool(normalized.validation_errors or normalized.structured_ui_errors)
                quality_issues = requested_native_quality_issues(parts, latest_user) if native_count else []
                call_usage = usage_records[call_usage_start:]
                outputs.append(
                    {
                        "case_id": case["id"],
                        "variant": variant,
                        "ui_mode": mode,
                        "selected_skill_ids": decision.get("selected_skill_ids", []),
                        "raw_response": raw_response,
                        "normalized_text": normalized.text,
                        "normalized_parts": parts,
                        "normalization": {
                            "validation_errors": normalized.validation_errors,
                            "structured_ui_errors": normalized.structured_ui_errors,
                            "artifact_status": normalized.artifact_status,
                            "artifact_reason_codes": normalized.artifact_reason_codes,
                            "structured_ui_repair_attempted": False,
                            "structured_ui_repair_succeeded": False,
                            "artifact_repair_attempted": False,
                            "json_validation_failed": validation_failed,
                            "structured_ui_quality_issues": quality_issues,
                            "native_block_count": native_count,
                            "artifact_count": artifact_count,
                            "first_pass_required_ui_parts_present": None if mode is None else required_parts_present,
                            "first_pass_mode_contract_satisfied": mode_contract_satisfied,
                        },
                        "elapsed_ms": elapsed_ms,
                        "first_response_chunk_ms": first_response_chunk_ms,
                        "first_pass_finish_reason": first_pass_finish_reason,
                        "output_chars": len(raw_response or ""),
                        "usage": [
                            {
                                "resource": item.resource,
                                "input_tokens": item.input_tokens,
                                "output_tokens": item.output_tokens,
                                "cost_nano_usd": item.cost_nano_usd,
                            }
                            for item in call_usage
                        ],
                        "cost_nano_usd": sum(item.cost_nano_usd for item in call_usage),
                    }
                )
    finally:
        llm_dynamic.max_output_tokens_for_model = output_limit_original
        set_usage_sink(None)

    report["calls"] = outputs
    report["actual_cost_nano_usd"] = sum(int(item["cost_nano_usd"]) for item in outputs)
    report["actual_cost_usd"] = _usd(report["actual_cost_nano_usd"])
    report.pop("plan", None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TypeError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
