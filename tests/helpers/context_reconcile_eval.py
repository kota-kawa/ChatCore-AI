# 記憶の照合（services/context_vault_reconcile.py）の回帰データセットを読み込み、使う前に形式を検証する。
# 期待値がデータ側に書かれているため、データが壊れていると判定が黙って甘くなる。読み込み時に機械的な検証を通し、壊れたデータは
# テストとして失敗させる。LLM の応答は固定で、文章の良し悪しではなく、コードが決める規則（応答の検証、対象 id の実在、状態による読み替え、
# 同じ対象への複数の update）だけを判定する。
# Loads the memory-reconciliation regression dataset and validates its shape before use. Expectations live in the data, so a
# broken case would silently weaken the checks; validation runs at load time and turns malformed data into a test failure.
# The LLM responses are frozen, and only the rules the code owns are judged (response validation, target existence, reading
# by state, several updates on one target), never the quality of any text.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from services.context_vault_reconcile import RelatedFact
from tests.helpers.llm_eval import EvalDatasetError

DATASET_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "llm_eval" / "context_reconcile_cases_v1.json"

_FACT_TYPES = frozenset({"preference", "profile", "project", "decision", "reference"})
_EXPECTED_ACTIONS = frozenset({"add", "supersede", "mention", "skip"})
_MEMORY_STATUSES = frozenset({"active", "deprecated"})


@dataclass(frozen=True)
class ReconcileCase:
    """照合 1 ケース。候補、候補ごとの近い記憶、固定した LLM の応答、候補ごとに期待する適用結果を持つ。

    One reconciliation case: the candidates, the nearby memories per candidate, the frozen LLM response and the
    expected outcome for every candidate.
    """

    case_id: str
    description: str
    candidates: list[dict[str, Any]]
    related_by_candidate: dict[int, list[RelatedFact]]
    response: str
    # 候補の添字から (期待する action, 対象の記憶の id または None)。
    # Candidate index to (expected action, target memory id or None).
    expected: dict[int, tuple[str, int | None]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvalDatasetError(message)


def _require_text(value: Any, label: str) -> str:
    _require(isinstance(value, str) and value.strip() != "", f"{label} must be a non-empty string")
    return str(value)


def _require_int(value: Any, label: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    return int(value)


# 日本語: ケースの memories を、label から RelatedFact への対応表にする。id と label の重複はデータ不備として弾く。
# English: Turn a case's memories into a label-to-RelatedFact map; duplicate ids or labels are dataset errors.
def _build_memories(case_id: str, raw_memories: Any) -> dict[str, RelatedFact]:
    _require(isinstance(raw_memories, list) and raw_memories, f"{case_id}: memories must be a non-empty list")
    memories: dict[str, RelatedFact] = {}
    seen_ids: set[int] = set()
    for raw in raw_memories:
        _require(isinstance(raw, dict), f"{case_id}: each memory must be an object")
        label = _require_text(raw.get("label"), f"{case_id}: memory label")
        _require(label not in memories, f"{case_id}: duplicate memory label {label}")
        fact_id = _require_int(raw.get("id"), f"{case_id}: memory {label} id")
        _require(fact_id not in seen_ids, f"{case_id}: duplicate memory id {fact_id}")
        seen_ids.add(fact_id)
        fact_type = _require_text(raw.get("fact_type"), f"{case_id}: memory {label} fact_type")
        _require(fact_type in _FACT_TYPES, f"{case_id}: memory {label} has an unknown fact_type")
        status = _require_text(raw.get("status"), f"{case_id}: memory {label} status")
        _require(status in _MEMORY_STATUSES, f"{case_id}: memory {label} has an unknown status")
        try:
            last_mentioned = date.fromisoformat(_require_text(raw.get("last_mentioned"), f"{case_id}: memory {label} last_mentioned"))
        except ValueError as exc:
            raise EvalDatasetError(f"{case_id}: memory {label} last_mentioned is not a date") from exc
        memories[label] = RelatedFact(
            fact_id=fact_id,
            revision=_require_int(raw.get("revision"), f"{case_id}: memory {label} revision"),
            fact_type=fact_type,
            title=_require_text(raw.get("title"), f"{case_id}: memory {label} title"),
            content=_require_text(raw.get("content"), f"{case_id}: memory {label} content"),
            status=status,  # type: ignore[arg-type]
            last_mentioned=last_mentioned,
        )
    return memories


# 日本語: 応答は文字列ならそのまま（壊れた応答のケース用）、オブジェクトなら target（記憶の label）を target_id へ置き換えて JSON にする。
# English: A string response is used as is (for malformed-response cases); an object response has each target (a memory label)
# replaced by its target_id before it is dumped as JSON.
def _build_response(case_id: str, raw: Any, memories: dict[str, RelatedFact]) -> str:
    if isinstance(raw, str):
        return raw
    _require(isinstance(raw, dict), f"{case_id}: response must be a string or an object")
    decisions = raw.get("decisions")
    if not isinstance(decisions, list):
        return json.dumps(raw, ensure_ascii=False)
    resolved: list[Any] = []
    for decision in decisions:
        if isinstance(decision, dict) and "target" in decision:
            label = decision["target"]
            _require(label in memories, f"{case_id}: response target {label!r} is not a memory label")
            decision = {key: value for key, value in decision.items() if key != "target"}
            decision["target_id"] = memories[label].fact_id
        resolved.append(decision)
    return json.dumps({**raw, "decisions": resolved}, ensure_ascii=False)


def _build_case(raw: Any) -> ReconcileCase:
    _require(isinstance(raw, dict), "each case must be an object")
    case_id = _require_text(raw.get("id"), "case id")
    memories = _build_memories(case_id, raw.get("memories"))

    raw_candidates = raw.get("candidates")
    _require(isinstance(raw_candidates, list) and raw_candidates, f"{case_id}: candidates must be a non-empty list")
    candidates: list[dict[str, Any]] = []
    related_by_candidate: dict[int, list[RelatedFact]] = {}
    for index, raw_candidate in enumerate(raw_candidates):
        _require(isinstance(raw_candidate, dict), f"{case_id}: each candidate must be an object")
        fact_type = _require_text(raw_candidate.get("fact_type"), f"{case_id}: candidate {index} fact_type")
        _require(fact_type in _FACT_TYPES, f"{case_id}: candidate {index} has an unknown fact_type")
        candidates.append(
            {
                "fact_type": fact_type,
                "title": _require_text(raw_candidate.get("title"), f"{case_id}: candidate {index} title"),
                "content": _require_text(raw_candidate.get("content"), f"{case_id}: candidate {index} content"),
            }
        )
        nearby = raw_candidate.get("nearby")
        _require(isinstance(nearby, list), f"{case_id}: candidate {index} nearby must be a list")
        for label in nearby:
            _require(label in memories, f"{case_id}: candidate {index} nearby {label!r} is not a memory label")
        _require(len(set(nearby)) == len(nearby), f"{case_id}: candidate {index} nearby has duplicates")
        related_by_candidate[index] = [memories[label] for label in nearby]

    raw_expect = raw.get("expect")
    _require(isinstance(raw_expect, list), f"{case_id}: expect must be a list")
    expected: dict[int, tuple[str, int | None]] = {}
    for item in raw_expect:
        _require(isinstance(item, dict), f"{case_id}: each expectation must be an object")
        index = _require_int(item.get("candidate"), f"{case_id}: expectation candidate")
        _require(0 <= index < len(candidates), f"{case_id}: expectation candidate {index} does not exist")
        _require(index not in expected, f"{case_id}: candidate {index} is expected twice")
        action = _require_text(item.get("action"), f"{case_id}: expectation action")
        _require(action in _EXPECTED_ACTIONS, f"{case_id}: unknown expected action {action}")
        target = item.get("target")
        if action == "add":
            _require(target is None, f"{case_id}: an expected add must not name a target")
            expected[index] = ("add", None)
            continue
        _require(target in memories, f"{case_id}: expected target {target!r} is not a memory label")
        expected[index] = (action, memories[target].fact_id)
    _require(set(expected) == set(range(len(candidates))), f"{case_id}: every candidate needs exactly one expectation")

    return ReconcileCase(
        case_id=case_id,
        description=_require_text(raw.get("description"), f"{case_id}: description"),
        candidates=candidates,
        related_by_candidate=related_by_candidate,
        response=_build_response(case_id, raw.get("response"), memories),
        expected=expected,
    )


def load_reconcile_dataset(path: Path = DATASET_PATH) -> list[ReconcileCase]:
    """データセットを読み込んで検証し、ケースの一覧を返す。壊れていれば EvalDatasetError。

    Load and validate the dataset, returning its cases; a malformed dataset raises EvalDatasetError.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalDatasetError(f"could not read {path.name}: {exc}") from exc
    _require(isinstance(raw, dict), "dataset must be an object")
    _require(isinstance(raw.get("dataset_id"), str) and raw["dataset_id"], "dataset_id is required")
    raw_cases = raw.get("cases")
    _require(isinstance(raw_cases, list) and raw_cases, "cases must be a non-empty list")
    cases = [_build_case(raw_case) for raw_case in raw_cases]
    case_ids = [case.case_id for case in cases]
    _require(len(case_ids) == len(set(case_ids)), "duplicate case ids")
    return cases
