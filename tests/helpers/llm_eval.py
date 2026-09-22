# チャット出力の回帰データセットを読み込み、使う前に形式を検証する。
# 期待値がデータ側に書かれているため、データが壊れていると判定が黙って甘くなる。
# 読み込み時に機械的な検証を通し、壊れたデータはテストとして失敗させる。
# Loads the chat-output regression dataset and validates its shape before use.
# Expectations live in the data, so a broken case would silently weaken the checks.
# Validation runs at load time and turns malformed data into a test failure.

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.generative_ui_status import (
    ARTIFACT_STATUS_INVALID,
    ARTIFACT_STATUS_MISSING,
    ARTIFACT_STATUS_NOT_REQUESTED,
    ARTIFACT_STATUS_SUPPRESSED,
    ARTIFACT_STATUS_VALID,
    REASON_ARTIFACT_MALFORMED,
    REASON_ARTIFACT_QUALITY_INSUFFICIENT,
    REASON_ARTIFACT_VALIDATION_FAILED,
    REASON_EXPLICIT_OPT_OUT,
    REASON_REQUIRED_ARTIFACT_MISSING,
)
from services.web_search import WebSearchResult, WebSearchSource

DATASET_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "llm_eval" / "chat_output_cases.json"

# 根拠IDはURLから決定的に作られるため、データセットには書かず label で参照する。
# Evidence ids are derived from the URL, so cases reference sources by label instead.
_CITE_PLACEHOLDER_RE = re.compile(r"\{\{cite(?P<style>|_fullwidth):(?P<label>[a-z0-9_]+)\}\}")

_CITATION_EXPECT_KEYS = frozenset({"citation_labels", "invalid_markers", "plain_text"})
_ARTIFACT_EXPECT_KEYS = frozenset({"artifact_status", "reason_codes", "quality_issue_labels"})
_ARTIFACT_STATUSES = frozenset(
    {
        ARTIFACT_STATUS_NOT_REQUESTED,
        ARTIFACT_STATUS_VALID,
        ARTIFACT_STATUS_MISSING,
        ARTIFACT_STATUS_INVALID,
        ARTIFACT_STATUS_SUPPRESSED,
    }
)
_ARTIFACT_REASON_CODES = frozenset(
    {
        REASON_EXPLICIT_OPT_OUT,
        REASON_REQUIRED_ARTIFACT_MISSING,
        REASON_ARTIFACT_MALFORMED,
        REASON_ARTIFACT_VALIDATION_FAILED,
        REASON_ARTIFACT_QUALITY_INSUFFICIENT,
    }
)
_UI_MODES = frozenset({"2D", "3D", "NONE"})


class EvalDatasetError(Exception):
    """Raised when the dataset itself is malformed."""


@dataclass(frozen=True)
class CitationCase:
    case_id: str
    description: str
    question: str
    result: WebSearchResult
    labels: dict[str, str]
    model_output: str
    expect: dict[str, Any]

    def expected_evidence_ids(self) -> list[str]:
        return [self.labels[label] for label in self.expect.get("citation_labels", [])]


@dataclass(frozen=True)
class ArtifactCase:
    case_id: str
    description: str
    ui_mode: str
    explicit_ui_opt_out: bool
    model_output: str
    expect: dict[str, Any]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvalDatasetError(message)


def _require_text(value: Any, label: str) -> str:
    _require(isinstance(value, str) and value.strip() != "", f"{label} must be a non-empty string")
    return str(value)


def _require_expect(raw: Any, allowed: frozenset[str], label: str) -> dict[str, Any]:
    _require(isinstance(raw, dict), f"{label} must be an object")
    unknown = sorted(set(raw) - allowed)
    _require(not unknown, f"{label} has unknown keys: {', '.join(unknown)}")
    return dict(raw)


def _require_string_list(value: Any, label: str) -> list[str]:
    _require(isinstance(value, list), f"{label} must be a list")
    for item in value:
        _require(isinstance(item, str) and item != "", f"{label} must hold non-empty strings")
    return list(value)


def _build_sources(case_id: str, raw_sources: Any) -> tuple[tuple[WebSearchSource, ...], dict[str, str]]:
    _require(isinstance(raw_sources, list) and raw_sources, f"{case_id}: sources must be a non-empty list")
    sources: list[WebSearchSource] = []
    labels: dict[str, str] = {}
    for raw_source in raw_sources:
        _require(isinstance(raw_source, dict), f"{case_id}: each source must be an object")
        label = _require_text(raw_source.get("label"), f"{case_id}: source label")
        _require(label not in labels, f"{case_id}: duplicate source label {label}")
        source = WebSearchSource(
            url=_require_text(raw_source.get("url"), f"{case_id}: source url"),
            title=_require_text(raw_source.get("title"), f"{case_id}: source title"),
            hostname=_require_text(raw_source.get("hostname"), f"{case_id}: source hostname"),
            age=str(raw_source.get("age") or ""),
            snippets=tuple(_require_string_list(raw_source.get("snippets", []), f"{case_id}: source snippets")),
        )
        _require(
            source.evidence_id not in labels.values(),
            f"{case_id}: two sources share the evidence id derived from their URL",
        )
        labels[label] = source.evidence_id
        sources.append(source)
    return tuple(sources), labels


def _render_citations(case_id: str, template: str, labels: dict[str, str]) -> str:
    # {{cite:label}} を回答内の引用marker へ展開する。未知の label はデータ不備として弾く。
    # Expand {{cite:label}} into the citation marker; an unknown label is a dataset error.
    def replace(match: re.Match[str]) -> str:
        label = match.group("label")
        _require(label in labels, f"{case_id}: model_output cites an unknown source label {label}")
        evidence_id = labels[label]
        if match.group("style") == "_fullwidth":
            return f"【{evidence_id}】"
        return f"[[source:{evidence_id}]]"

    rendered = _CITE_PLACEHOLDER_RE.sub(replace, template)
    _require("{{cite" not in rendered, f"{case_id}: model_output has a malformed citation placeholder")
    return rendered


def _build_citation_case(raw: Any) -> CitationCase:
    _require(isinstance(raw, dict), "citation case must be an object")
    case_id = _require_text(raw.get("id"), "citation case id")
    description = _require_text(raw.get("description"), f"{case_id}: description")
    question = _require_text(raw.get("question"), f"{case_id}: question")
    template = _require_text(raw.get("model_output"), f"{case_id}: model_output")

    sources, labels = _build_sources(case_id, raw.get("sources"))
    model_output = _render_citations(case_id, template, labels)

    expect = _require_expect(raw.get("expect"), _CITATION_EXPECT_KEYS, f"{case_id}: expect")
    expected_labels = _require_string_list(expect.get("citation_labels", []), f"{case_id}: citation_labels")
    unknown_labels = sorted(set(expected_labels) - set(labels))
    _require(not unknown_labels, f"{case_id}: expects unknown source labels: {', '.join(unknown_labels)}")
    # 不正 marker も label 参照で書けるようにする。根拠IDを手書きすると、ID の作り方が
    # 変わった瞬間にデータだけが古くなる。
    # Invalid markers are written with labels too: a hand-written evidence id would go stale
    # the moment the id derivation changes.
    expect["invalid_markers"] = [
        _render_citations(case_id, marker, labels)
        for marker in _require_string_list(expect.get("invalid_markers", []), f"{case_id}: invalid_markers")
    ]
    for marker in expect["invalid_markers"]:
        _require(marker in model_output, f"{case_id}: invalid marker {marker} is absent from model_output")
    _require(
        len(expected_labels)
        == model_output.count("[[source:") + model_output.count("【src_") - len(expect["invalid_markers"]),
        f"{case_id}: citation_labels must account for every marker that is not listed as invalid",
    )
    plain_text = _require_text(expect.get("plain_text"), f"{case_id}: plain_text")
    _require(
        "[[source:" not in plain_text and "【src_" not in plain_text,
        f"{case_id}: plain_text must be the prose left after citations are rendered",
    )

    result = WebSearchResult(
        query=_require_text(raw.get("query", question), f"{case_id}: query"),
        searched_at=str(raw.get("searched_at") or "2026-06-01T00:00:00Z"),
        sources=sources,
    )
    return CitationCase(
        case_id=case_id,
        description=description,
        question=question,
        result=result,
        labels=labels,
        model_output=model_output,
        expect=expect,
    )


def _artifact_model_output(case_id: str, raw: dict[str, Any]) -> str:
    artifact = raw.get("artifact")
    prose = _require_text(raw.get("prose"), f"{case_id}: prose")
    if artifact is None:
        return prose
    _require(isinstance(artifact, dict), f"{case_id}: artifact must be an object")
    block = json.dumps(artifact, ensure_ascii=False)
    return f"{prose}\n\n```chatcore-artifact\n{block}\n```"


def _build_artifact_case(raw: Any) -> ArtifactCase:
    _require(isinstance(raw, dict), "artifact case must be an object")
    case_id = _require_text(raw.get("id"), "artifact case id")
    description = _require_text(raw.get("description"), f"{case_id}: description")
    ui_mode = _require_text(raw.get("ui_mode"), f"{case_id}: ui_mode")
    _require(ui_mode in _UI_MODES, f"{case_id}: unknown ui_mode {ui_mode}")

    opt_out = raw.get("explicit_ui_opt_out", False)
    _require(isinstance(opt_out, bool), f"{case_id}: explicit_ui_opt_out must be a boolean")

    expect = _require_expect(raw.get("expect"), _ARTIFACT_EXPECT_KEYS, f"{case_id}: expect")
    status = _require_text(expect.get("artifact_status"), f"{case_id}: artifact_status")
    _require(status in _ARTIFACT_STATUSES, f"{case_id}: unknown artifact_status {status}")

    reason_codes = _require_string_list(expect.get("reason_codes", []), f"{case_id}: reason_codes")
    unknown_codes = sorted(set(reason_codes) - _ARTIFACT_REASON_CODES)
    _require(not unknown_codes, f"{case_id}: unknown reason codes: {', '.join(unknown_codes)}")

    # 品質ゲートの期待は「どの指摘が出るか」まで書く。null は「このケースでは評価しない」。
    # The gate expectation lists which issues must fire; null means the gate is not evaluated.
    issue_labels = expect.get("quality_issue_labels")
    if issue_labels is None:
        _require(
            ui_mode == "NONE" or status != ARTIFACT_STATUS_VALID,
            f"{case_id}: a requested and valid artifact must state its quality_issue_labels",
        )
    else:
        _require_string_list(issue_labels, f"{case_id}: quality_issue_labels")
        _require(
            ui_mode in {"2D", "3D"},
            f"{case_id}: quality_issue_labels only applies to a requested 2D or 3D artifact",
        )

    return ArtifactCase(
        case_id=case_id,
        description=description,
        ui_mode=ui_mode,
        explicit_ui_opt_out=opt_out,
        model_output=_artifact_model_output(case_id, raw),
        expect=expect,
    )


def load_dataset(path: Path | None = None) -> tuple[tuple[CitationCase, ...], tuple[ArtifactCase, ...]]:
    # データセットを読み込み、形式・参照関係・ID の重複を検証してから返す。
    # Load the dataset and validate shape, references, and duplicate ids before returning it.
    dataset_path = path or DATASET_PATH
    _require(dataset_path.is_file(), f"dataset is missing: {dataset_path}")
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    _require(isinstance(raw, dict), "dataset must be an object")
    unknown = sorted(set(raw) - {"citation_cases", "artifact_cases"})
    _require(not unknown, f"dataset has unknown keys: {', '.join(unknown)}")

    raw_citations = raw.get("citation_cases")
    raw_artifacts = raw.get("artifact_cases")
    _require(isinstance(raw_citations, list) and raw_citations, "citation_cases must be a non-empty list")
    _require(isinstance(raw_artifacts, list) and raw_artifacts, "artifact_cases must be a non-empty list")

    citation_cases = tuple(_build_citation_case(item) for item in raw_citations)
    artifact_cases = tuple(_build_artifact_case(item) for item in raw_artifacts)

    case_ids = [case.case_id for case in citation_cases] + [case.case_id for case in artifact_cases]
    duplicates = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
    _require(not duplicates, f"dataset reuses case ids: {', '.join(duplicates)}")

    return citation_cases, artifact_cases
