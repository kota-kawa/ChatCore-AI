#!/usr/bin/env python3
"""Compare a Git baseline and the working-tree Skill selection on fixed Issue 870 cases.

Dry-run by default. Pass ``--execute`` to make serial provider calls after the
input, output, call-count, and estimated-cost caps pass preflight.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Protocol, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if TYPE_CHECKING:
    from services.repositories.usage_repository import UsageIncrement

DATASET_PATH = ROOT / "tests/fixtures/llm_eval/generative_ui_mode_selection_cases_v1.json"
MAX_INPUT_TOKENS_PER_CALL = 8_000
MAX_OUTPUT_TOKENS_PER_CALL = 8_192
MAX_CALLS = 20
DEFAULT_MODEL = "openai/gpt-oss-120b"


class OutputTokenLimit(Protocol):
    def __call__(self, model_name: str | None, generation_phase: str = "default") -> int: ...


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Call the configured model; default is dry-run.")
    parser.add_argument("--baseline-ref", default="origin/main", help="Git ref for the baseline source (default: origin/main).")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model used for both variants (default: {DEFAULT_MODEL}).")
    parser.add_argument("--repeats", type=int, default=2, help="Serial baseline/after comparisons per case (default: 2).")
    parser.add_argument("--case", action="append", dest="case_ids", help="Limit to a case id; repeat the option to select several.")
    parser.add_argument("--input-cap-tokens", type=int, default=MAX_INPUT_TOKENS_PER_CALL)
    parser.add_argument("--output-cap-tokens", type=int, default=MAX_OUTPUT_TOKENS_PER_CALL)
    parser.add_argument("--max-estimated-usd", type=Decimal, default=Decimal("1.00"))
    return parser.parse_args()


def _source_from_ref(relative_path: str, baseline_ref: str) -> str:
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


def _working_tree_fingerprint(relative_paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative_path in relative_paths:
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update((ROOT / relative_path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _exec_module(name: str, source: str) -> ModuleType:
    module = ModuleType(name)
    module.__package__ = "services"
    sys.modules[name] = module
    exec(compile(source, name, "exec"), module.__dict__)
    return module


def _load_baseline_services(current_user_skills: ModuleType, baseline_ref: str) -> tuple[ModuleType, ModuleType]:
    legacy_skills = _exec_module(
        "services._issue870_baseline_user_skills",
        _source_from_ref("services/user_skills.py", baseline_ref),
    )
    previous_user_skills = sys.modules["services.user_skills"]
    sys.modules["services.user_skills"] = legacy_skills
    try:
        legacy_selection = _exec_module(
            "services._issue870_baseline_chat_skill_selection",
            _source_from_ref("services/chat_skill_selection.py", baseline_ref),
        )
    finally:
        sys.modules["services.user_skills"] = current_user_skills or previous_user_skills
    return legacy_skills, legacy_selection


def _context(user_skills_module: ModuleType) -> Any:
    return user_skills_module.build_chat_skills_context(
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


def _classifier_messages(
    selection_module: ModuleType,
    user_skills_module: ModuleType,
    case: dict[str, Any],
    model_name: str,
) -> list[dict[str, str]]:
    captured: list[list[dict[str, str]]] = []
    context = _context(user_skills_module)

    def capture(messages: list[dict[str, str]], _model: str) -> str:
        captured.append(messages)
        return json.dumps({"selected_skill_ids": [], "uncertain": False, "ui_mode": "NONE"})

    latest_user = next(
        (message["content"] for message in reversed(case["messages"]) if message["role"] == "user"),
        "",
    )
    forbidden = importlib.import_module("services.generative_ui_intent").is_explicit_generative_ui_opt_out(latest_user)
    selection_module.select_chat_skills(
        context,
        case["messages"],
        model_name,
        llm_json_response=capture,
        generative_ui_forbidden=forbidden,
    )
    if captured:
        return captured[0]

    # If explicit opt-out removed the sole candidate, the implementation correctly
    # skips classification. Use its exact message builder to estimate the skipped request.
    return cast(list[dict[str, str]], selection_module._build_classifier_messages(
        context.candidates,
        case["messages"],
        "",
        "",
        ui_allowed=False,
    ))


def _load_dataset(case_ids: list[str] | None) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    raw = DATASET_PATH.read_bytes()
    dataset = json.loads(raw)
    cases = dataset["cases"]
    if case_ids:
        known = {case["id"] for case in cases}
        unknown = set(case_ids) - known
        if unknown:
            raise ValueError(f"Unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in set(case_ids)]
    if not cases:
        raise ValueError("No evaluation cases selected.")
    return dataset, cases, hashlib.sha256(raw).hexdigest()


def _build_plan(
    args: argparse.Namespace,
    cases: list[dict[str, Any]],
    modules: tuple[ModuleType, ModuleType, ModuleType, ModuleType],
) -> list[dict[str, Any]]:
    from services.llm_context_budget import estimate_messages_tokens
    from services.usage_pricing import token_cost_nano_usd

    legacy_skills, legacy_selection, current_skills, current_selection = modules
    ui_intent = importlib.import_module("services.generative_ui_intent")
    plan: list[dict[str, Any]] = []
    for case in cases:
        for repeat in range(1, args.repeats + 1):
            for variant, skills_module, selection_module in (
                ("baseline", legacy_skills, legacy_selection),
                ("after", current_skills, current_selection),
            ):
                context = _context(skills_module)
                latest_user = next(
                    (message["content"] for message in reversed(case["messages"]) if message["role"] == "user"),
                    "",
                )
                forbidden = ui_intent.is_explicit_generative_ui_opt_out(latest_user)
                decision_candidates = tuple(
                    candidate
                    for candidate in context.candidates
                    if candidate.id != 0 or not forbidden
                )
                if not decision_candidates:
                    plan.append(
                        {
                            "case_id": case["id"],
                            "repeat": repeat,
                            "variant": variant,
                            "api_call": False,
                            "input_tokens_estimate": 0,
                            "output_tokens_cap": 0,
                            "estimated_cost_nano_usd": 0,
                        }
                    )
                    continue
                messages = _classifier_messages(selection_module, skills_module, case, args.model)
                input_tokens = estimate_messages_tokens(messages)
                if input_tokens > args.input_cap_tokens:
                    raise ValueError(
                        f"{case['id']} {variant} input estimate {input_tokens} exceeds "
                        f"the {args.input_cap_tokens}-token cap."
                    )
                cost = token_cost_nano_usd(
                    args.model,
                    input_tokens=input_tokens,
                    output_tokens=args.output_cap_tokens,
                )
                plan.append(
                    {
                        "case_id": case["id"],
                        "repeat": repeat,
                        "variant": variant,
                        "api_call": True,
                        "input_tokens_estimate": input_tokens,
                        "output_tokens_cap": args.output_cap_tokens,
                        "estimated_cost_nano_usd": cost,
                    }
                )
    return plan


def _usd(nano_usd: int) -> str:
    return f"{Decimal(nano_usd) / Decimal(1_000_000_000):.6f}"


def main() -> int:
    args = _parse_args()
    if args.repeats < 1:
        raise ValueError("--repeats must be at least 1.")
    if not 1 <= args.input_cap_tokens <= MAX_INPUT_TOKENS_PER_CALL:
        raise ValueError(f"--input-cap-tokens must be between 1 and {MAX_INPUT_TOKENS_PER_CALL}.")
    if not 1 <= args.output_cap_tokens <= MAX_OUTPUT_TOKENS_PER_CALL:
        raise ValueError(f"--output-cap-tokens must be between 1 and {MAX_OUTPUT_TOKENS_PER_CALL}.")

    dataset, cases, dataset_sha256 = _load_dataset(args.case_ids)
    # Load app configuration before importing services.llm, which constructs provider clients.
    # The values are only read by the application and are never printed or added to the report.
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    from services.usage_metering import set_usage_sink

    current_skills = importlib.import_module("services.user_skills")
    current_selection = importlib.import_module("services.chat_skill_selection")
    legacy_skills, legacy_selection = _load_baseline_services(current_skills, args.baseline_ref)
    llm = importlib.import_module("services.llm")
    llm.validate_model_name(args.model)
    if not llm.is_groq_model(args.model):
        raise ValueError("This script caps output through the Groq response path; choose a supported Groq model.")
    modules = (legacy_skills, legacy_selection, current_skills, current_selection)
    plan = _build_plan(args, cases, modules)
    call_count = sum(1 for item in plan if item["api_call"])
    if call_count > MAX_CALLS:
        raise ValueError(f"Planned {call_count} calls exceeds the {MAX_CALLS}-call script limit.")
    estimated_cost = sum(item["estimated_cost_nano_usd"] for item in plan)
    budget_nano_usd = int(args.max_estimated_usd * Decimal(1_000_000_000))
    if estimated_cost > budget_nano_usd:
        raise ValueError(
            f"Estimated cost ${_usd(estimated_cost)} exceeds --max-estimated-usd "
            f"${args.max_estimated_usd}."
        )

    report: dict[str, Any] = {
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": dataset_sha256,
        "baseline_ref": args.baseline_ref,
        "baseline_commit_hash": _commit_hash(args.baseline_ref),
        "after_source_fingerprint": _working_tree_fingerprint(
            (
                "services/chat_skill_selection.py",
                "services/user_skills.py",
                "services/generative_ui_intent.py",
            )
        ),
        "model": args.model,
        "calls_planned": call_count,
        "input_cap_tokens_per_call": args.input_cap_tokens,
        "output_cap_tokens_per_call": args.output_cap_tokens,
        "estimated_max_cost_usd": _usd(estimated_cost),
        "cases": [case["id"] for case in cases],
        "plan": plan,
    }
    if not args.execute:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(
        f"Issue 870 comparison preflight: {call_count} serial calls, max estimated cost ${_usd(estimated_cost)}.",
        file=sys.stderr,
    )
    usage_records: list[UsageIncrement] = []
    set_usage_sink(usage_records.append)
    outputs: list[dict[str, Any]] = []
    try:
        llm_dynamic = cast(Any, llm)
        original_output_limit = cast(OutputTokenLimit, llm_dynamic.max_output_tokens_for_model)
        output_cap_tokens = int(args.output_cap_tokens)

        def capped_output_limit(model_name: str, generation_phase: str = "default") -> int:
            return min(original_output_limit(model_name, generation_phase), output_cap_tokens)

        llm_dynamic.max_output_tokens_for_model = capped_output_limit
        try:
            for case in cases:
                latest_user = next(
                    (message["content"] for message in reversed(case["messages"]) if message["role"] == "user"),
                    "",
                )
                forbidden = importlib.import_module("services.generative_ui_intent").is_explicit_generative_ui_opt_out(
                    latest_user
                )
                for repeat in range(1, args.repeats + 1):
                    for variant, skills_module, selection_module in (
                        ("baseline", legacy_skills, legacy_selection),
                        ("after", current_skills, current_selection),
                    ):
                        call_usage_start = len(usage_records)
                        raw_response: str | None = None
                        request_sent = False

                        def invoke(messages: list[dict[str, str]], model_name: str) -> str | None:
                            nonlocal raw_response, request_sent
                            request_sent = True
                            raw_response = llm.get_llm_json_response(
                                messages,
                                model_name,
                                generation_phase=llm.SKILL_SELECTION_GENERATION_PHASE,
                            )
                            return raw_response

                        result = selection_module.select_chat_skills(
                            _context(skills_module),
                            case["messages"],
                            args.model,
                            llm_json_response=invoke,
                            generative_ui_forbidden=forbidden,
                        )
                        call_usage = usage_records[call_usage_start:]
                        outputs.append(
                            {
                                "case_id": case["id"],
                                "repeat": repeat,
                                "variant": variant,
                                "api_call": request_sent,
                                "raw_response": raw_response,
                                "ui_mode": result.ui_mode,
                                "selected_skill_ids": result.telemetry["selected_skill_ids"],
                                "fallback": result.telemetry["fallback"],
                                "reason": result.telemetry["reason"],
                                "matches_expected_mode": result.ui_mode == case["expect"][
                                    "baseline_ui_mode" if variant == "baseline" else "ui_mode"
                                ],
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
            llm_dynamic.max_output_tokens_for_model = original_output_limit
    finally:
        set_usage_sink(None)

    report["calls"] = outputs
    report["actual_cost_nano_usd"] = sum(item["cost_nano_usd"] for item in outputs)
    report["actual_cost_usd"] = _usd(report["actual_cost_nano_usd"])
    report.pop("plan", None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
