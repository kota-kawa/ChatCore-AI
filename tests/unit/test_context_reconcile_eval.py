"""固定した記憶の照合データセットの読み込み検証と、判定の適用規則が記録した期待どおりかを確かめるテスト。

Tests that the frozen memory-reconciliation dataset validates, and that the decision-application rules match the
recorded expectations. Only the rules the code owns are judged, never the quality of any text.
"""

import json
import tempfile
import unittest
from pathlib import Path

from services.context_vault_reconcile import (
    CandidatePlan,
    ReconcileResolution,
    build_reconcile_messages,
    resolve_candidate_action,
    resolve_reconcile_decisions,
)
from tests.helpers.context_reconcile_eval import DATASET_PATH, ReconcileCase, load_reconcile_dataset
from tests.helpers.llm_eval import EvalDatasetError


class ContextReconcileDatasetTestCase(unittest.TestCase):
    def test_dataset_identifier_is_the_frozen_generation(self):
        # このデータセットはこの PR で新しく足したので、マージ時の内容を v1 として固定する（他のデータセットも v1 のまま）。
        # The dataset is new in this PR, so its content at merge is frozen as v1 (the other datasets are all v1 as well).
        self.assertEqual(json.loads(DATASET_PATH.read_text(encoding="utf-8"))["dataset_id"], "context-reconcile-v1")

    def test_dataset_loads_and_passes_validation(self):
        cases = load_reconcile_dataset()

        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len({case.case_id for case in cases}), len(cases))

    def test_dataset_covers_every_outcome_and_the_state_dependent_rules(self):
        cases = load_reconcile_dataset()

        outcomes = {action for case in cases for action, _target in case.expected.values()}
        self.assertEqual(outcomes, {"add", "supersede", "mention", "skip"})
        statuses = {fact.status for case in cases for related in case.related_by_candidate.values() for fact in related}
        self.assertEqual(statuses, {"active", "deprecated"})

    def test_dataset_validation_rejects_a_dangling_memory_label(self):
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["cases"][0]["candidates"][0]["nearby"] = ["not_a_memory"]

        self._assert_rejected(broken)

    def test_dataset_validation_rejects_a_candidate_without_an_expectation(self):
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["cases"][0]["expect"] = []

        self._assert_rejected(broken)

    def test_dataset_validation_rejects_an_expected_add_that_names_a_target(self):
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["cases"][2]["expect"][0]["target"] = "review_language"

        self._assert_rejected(broken)

    def test_dataset_validation_rejects_duplicate_memory_ids(self):
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        case = next(case for case in broken["cases"] if case["id"] == "target_from_another_candidates_list")
        case["memories"][1]["id"] = case["memories"][0]["id"]

        self._assert_rejected(broken)

    def test_dataset_validation_rejects_a_removed_duplicate_flag_without_a_bm25_match(self):
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["cases"][0]["candidates"][0]["duplicates_owner_removed"] = True

        self._assert_rejected(broken)

    def test_dataset_validation_rejects_a_response_target_that_is_not_a_memory(self):
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["cases"][0]["response"]["decisions"][0]["target"] = "not_a_memory"

        self._assert_rejected(broken)

    # 壊したデータセットを一時ファイルへ書き出し、読み込みが EvalDatasetError で拒否することを確かめる。
    # Writes a broken dataset to a temp file and checks loading rejects it with EvalDatasetError.
    def _assert_rejected(self, dataset: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(EvalDatasetError):
                load_reconcile_dataset(path)


# 日本語: 事前の照合の結果（plan）と、保存の段で見た BM25 の一致が同じ記憶になるものとして、候補ごとの最終的な保存の仕方を返します。
# English: The final way each candidate is stored, taking the BM25 match at the save stage to be the same memory as before reconciliation.
def _final_resolutions(case: ReconcileCase) -> dict[int, ReconcileResolution]:
    decided = resolve_reconcile_decisions(case.response, case.related_by_candidate)
    finals: dict[int, ReconcileResolution] = {}
    for index in range(len(case.candidates)):
        matched = case.matched.get(index)
        plan = CandidatePlan(
            resolution=decided.get(index),
            matched_fact_id=matched.fact_id if matched else None,
        )
        finals[index] = resolve_candidate_action(
            plan,
            matched.fact_id if matched else None,
            matched.revision if matched else None,
            duplicates_owner_removed=index in case.duplicates_owner_removed,
        )
    return finals


class ContextReconcileEvalTestCase(unittest.TestCase):
    def test_every_case_resolves_to_the_recorded_outcome(self):
        for case in load_reconcile_dataset():
            with self.subTest(case.case_id):
                actual = {index: (final.action, final.target_fact_id) for index, final in _final_resolutions(case).items()}

                self.assertEqual(actual, case.expected, case.description)

    def test_a_supersede_or_mention_carries_the_revision_that_was_read(self):
        for case in load_reconcile_dataset():
            with self.subTest(case.case_id):
                revisions = {fact.fact_id: fact.revision for related in case.related_by_candidate.values() for fact in related}

                for final in _final_resolutions(case).values():
                    self.assertIsInstance(final, ReconcileResolution)
                    if final.action != "add":
                        self.assertEqual(final.target_revision, revisions[final.target_fact_id])

    def test_no_case_supersedes_a_memory_twice_or_supersedes_a_deactivated_one(self):
        for case in load_reconcile_dataset():
            with self.subTest(case.case_id):
                statuses = {fact.fact_id: fact.status for related in case.related_by_candidate.values() for fact in related}

                superseded = [final.target_fact_id for final in _final_resolutions(case).values() if final.action == "supersede"]
                self.assertEqual(len(superseded), len(set(superseded)))
                for target_id in superseded:
                    self.assertEqual(statuses[target_id], "active")

    def test_no_case_adds_a_source_to_a_memory_that_another_candidate_supersedes(self):
        for case in load_reconcile_dataset():
            with self.subTest(case.case_id):
                finals = _final_resolutions(case).values()

                superseded = {final.target_fact_id for final in finals if final.action == "supersede"}
                mentioned = {final.target_fact_id for final in finals if final.action == "mention"}
                self.assertFalse(superseded & mentioned)

    def test_no_case_creates_a_new_memory_for_a_candidate_that_also_duplicates_removed_content(self):
        for case in load_reconcile_dataset():
            with self.subTest(case.case_id):
                finals = _final_resolutions(case)

                for index in case.duplicates_owner_removed:
                    self.assertNotIn(finals[index].action, ("add", "supersede"))

    def test_the_dataset_covers_candidates_that_duplicate_removed_content_under_every_decision(self):
        cases = [case for case in load_reconcile_dataset() if case.duplicates_owner_removed]

        self.assertGreaterEqual(len(cases), 5)
        self.assertTrue(any(case.response is None for case in cases), "an LLM failure case is required")

    def test_the_dataset_covers_bm25_matched_candidates_with_every_outcome_and_the_failure_fallback(self):
        cases = [case for case in load_reconcile_dataset() if case.matched]

        outcomes = {
            (case.case_id, final.action)
            for case in cases
            for index, final in _final_resolutions(case).items()
            if index in case.matched
        }
        self.assertTrue({"add", "supersede", "mention", "skip"} <= {action for _id, action in outcomes})
        self.assertTrue(any(case.response is None for case in cases), "an LLM failure case is required")

    def test_every_case_builds_a_prompt_that_shows_only_candidates_with_nearby_memory(self):
        for case in load_reconcile_dataset():
            with self.subTest(case.case_id):
                messages = build_reconcile_messages(case.candidates, case.related_by_candidate)

                payload = json.loads(messages[1]["content"])
                shown = {candidate["index"] for candidate in payload["candidates"]}
                self.assertEqual(shown, {index for index, related in case.related_by_candidate.items() if related})
                shown_ids = {memory["id"] for memory in payload["memories"]}
                for candidate in payload["candidates"]:
                    self.assertTrue(set(candidate["nearby_memory_ids"]) <= shown_ids)


if __name__ == "__main__":
    unittest.main()
