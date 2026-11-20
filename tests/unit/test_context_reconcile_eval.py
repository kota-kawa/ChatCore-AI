"""固定した記憶の照合データセットの読み込み検証と、判定の適用規則が記録した期待どおりかを確かめるテスト。

Tests that the frozen memory-reconciliation dataset validates, and that the decision-application rules match the
recorded expectations. Only the rules the code owns are judged, never the quality of any text.
"""

import json
import tempfile
import unittest
from pathlib import Path

from services.context_vault_reconcile import (
    ReconcileResolution,
    build_reconcile_messages,
    resolve_reconcile_decisions,
)
from tests.helpers.context_reconcile_eval import DATASET_PATH, load_reconcile_dataset
from tests.helpers.llm_eval import EvalDatasetError


class ContextReconcileDatasetTestCase(unittest.TestCase):
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


class ContextReconcileEvalTestCase(unittest.TestCase):
    def test_every_case_resolves_to_the_recorded_outcome(self):
        for case in load_reconcile_dataset():
            with self.subTest(case.case_id):
                resolutions = resolve_reconcile_decisions(case.response, case.related_by_candidate)

                actual = {
                    index: (resolutions[index].action, resolutions[index].target_fact_id) if index in resolutions else ("add", None)
                    for index in range(len(case.candidates))
                }
                self.assertEqual(actual, case.expected, case.description)

    def test_a_supersede_or_mention_carries_the_revision_that_was_read(self):
        for case in load_reconcile_dataset():
            with self.subTest(case.case_id):
                revisions = {fact.fact_id: fact.revision for related in case.related_by_candidate.values() for fact in related}
                resolutions = resolve_reconcile_decisions(case.response, case.related_by_candidate)

                for resolution in resolutions.values():
                    self.assertIsInstance(resolution, ReconcileResolution)
                    self.assertEqual(resolution.target_revision, revisions[resolution.target_fact_id])

    def test_no_case_supersedes_a_memory_twice_or_supersedes_a_deactivated_one(self):
        for case in load_reconcile_dataset():
            with self.subTest(case.case_id):
                statuses = {fact.fact_id: fact.status for related in case.related_by_candidate.values() for fact in related}
                resolutions = resolve_reconcile_decisions(case.response, case.related_by_candidate)

                superseded = [resolution.target_fact_id for resolution in resolutions.values() if resolution.action == "supersede"]
                self.assertEqual(len(superseded), len(set(superseded)))
                for target_id in superseded:
                    self.assertEqual(statuses[target_id], "active")

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
