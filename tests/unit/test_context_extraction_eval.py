"""固定した機微な内容の抽出データセットの読み込み検証と、抽出の検証規則が記録した期待どおりかを確かめるテスト。

Tests that the frozen sensitive-content extraction dataset validates, and that the extraction validation rules match the
recorded expectations. Only the rules the code owns are judged, never the quality of any text.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from services.context_vault_extraction import extract_context_candidates
from tests.helpers.context_extraction_eval import DATASET_PATH, load_extraction_dataset
from tests.helpers.llm_eval import EvalDatasetError


class ContextExtractionDatasetTestCase(unittest.TestCase):
    def test_dataset_identifier_is_the_frozen_generation(self):
        self.assertEqual(json.loads(DATASET_PATH.read_text(encoding="utf-8"))["dataset_id"], "context-extraction-sensitive-v1")

    def test_dataset_loads_and_covers_accepted_and_dropped_outcomes(self):
        cases = load_extraction_dataset()

        self.assertGreaterEqual(len(cases), 12)
        self.assertTrue(any(case.accepted_titles for case in cases))
        self.assertTrue(any(not case.accepted_titles for case in cases))

    def test_dataset_validation_rejects_an_expected_title_that_is_not_a_candidate(self):
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["cases"][0]["expect_accepted"] = ["not a candidate"]

        self._assert_rejected(broken)

    def test_dataset_validation_rejects_duplicate_case_ids(self):
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["cases"][1]["id"] = broken["cases"][0]["id"]

        self._assert_rejected(broken)

    def test_dataset_validation_rejects_a_case_without_a_user_message(self):
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["cases"][0]["user_message"] = ""

        self._assert_rejected(broken)

    # 壊したデータセットを一時ファイルへ書き出し、読み込みが EvalDatasetError で拒否することを確かめる。
    # Writes a broken dataset to a temp file and checks loading rejects it with EvalDatasetError.
    def _assert_rejected(self, dataset: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(EvalDatasetError):
                load_extraction_dataset(path)


class ContextExtractionEvalTestCase(unittest.TestCase):
    def test_every_case_accepts_exactly_the_recorded_candidates(self):
        for case in load_extraction_dataset():
            with self.subTest(case.case_id):
                accepted = extract_context_candidates(
                    case.user_message,
                    case.assistant_response,
                    llm_json_response=Mock(return_value=case.response),
                )

                self.assertEqual([candidate["title"] for candidate in accepted], case.accepted_titles, case.description)

    def test_accepted_candidates_never_carry_the_verification_only_fields(self):
        for case in load_extraction_dataset():
            with self.subTest(case.case_id):
                accepted = extract_context_candidates(
                    case.user_message,
                    case.assistant_response,
                    llm_json_response=Mock(return_value=case.response),
                )

                for candidate in accepted:
                    self.assertNotIn("sensitive_category", candidate)
                    self.assertNotIn("request_evidence", candidate)


if __name__ == "__main__":
    unittest.main()
