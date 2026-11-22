# 記憶の候補の抽出（services/context_vault_extraction.py）の機微な内容の規則について、回帰データセットを読み込み、使う前に形式を検証する。
# 期待値がデータ側に書かれているため、データが壊れていると判定が黙って甘くなる。読み込み時に機械的な検証を通し、壊れたデータは
# テストとして失敗させる。LLM の応答は固定で、文章の良し悪しではなく、コードが決める規則（応答の検証、依頼の一節の照合）だけを判定する。
# Loads the regression dataset for the sensitive-content rule of memory-candidate extraction and validates its shape before use.
# Expectations live in the data, so a broken case would silently weaken the checks; validation runs at load time and turns
# malformed data into a test failure. The LLM responses are frozen, and only the rules the code owns are judged (response
# validation, matching the span that asks to remember a sensitive candidate), never the quality of any text.

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.helpers.llm_eval import EvalDatasetError

DATASET_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "llm_eval" / "context_extraction_sensitive_cases_v1.json"


@dataclass(frozen=True)
class ExtractionCase:
    """抽出 1 ケース。利用者の発話、アシスタントの応答、固定した LLM の応答（JSON 文字列）、通るはずの候補の題名を持つ。

    One extraction case: the user's message, the assistant's response, the frozen LLM response (a JSON string) and the titles
    of the candidates that must be accepted.
    """

    case_id: str
    description: str
    user_message: str
    assistant_response: str
    response: str
    accepted_titles: list[str]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvalDatasetError(message)


def _require_text(value: Any, label: str) -> str:
    _require(isinstance(value, str) and value.strip() != "", f"{label} must be a non-empty string")
    return str(value)


def _build_case(raw: Any) -> ExtractionCase:
    _require(isinstance(raw, dict), "each case must be an object")
    case_id = _require_text(raw.get("id"), "case id")
    response = raw.get("response")
    _require(isinstance(response, dict), f"{case_id}: response must be an object")
    raw_candidates = response.get("candidates")
    _require(isinstance(raw_candidates, list), f"{case_id}: response candidates must be a list")
    titles = []
    for candidate in raw_candidates:
        _require(isinstance(candidate, dict), f"{case_id}: each candidate must be an object")
        titles.append(_require_text(candidate.get("title"), f"{case_id}: candidate title"))
    _require(len(set(titles)) == len(titles), f"{case_id}: candidate titles must be unique")
    accepted = raw.get("expect_accepted")
    _require(isinstance(accepted, list), f"{case_id}: expect_accepted must be a list")
    for title in accepted:
        _require(title in titles, f"{case_id}: expected title {title!r} is not a candidate of the response")
    _require(len(set(accepted)) == len(accepted), f"{case_id}: expect_accepted has duplicates")
    assistant_response = raw.get("assistant_response")
    _require(isinstance(assistant_response, str), f"{case_id}: assistant_response must be a string")
    return ExtractionCase(
        case_id=case_id,
        description=_require_text(raw.get("description"), f"{case_id}: description"),
        user_message=_require_text(raw.get("user_message"), f"{case_id}: user_message"),
        assistant_response=assistant_response,
        response=json.dumps(response, ensure_ascii=False),
        accepted_titles=list(accepted),
    )


def load_extraction_dataset(path: Path = DATASET_PATH) -> list[ExtractionCase]:
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
