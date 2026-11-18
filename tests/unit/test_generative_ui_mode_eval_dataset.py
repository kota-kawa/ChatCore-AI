"""Fixed cases for comparing the legacy and preselected generative-UI modes."""

import json
import unittest
from pathlib import Path

DATASET_PATH = Path(__file__).resolve().parents[1] / "fixtures/llm_eval/generative_ui_mode_selection_cases_v1.json"
LEGACY_MODES = {"NONE", "2D", "3D"}
CURRENT_MODES = {"NONE", "STRUCTURED_UI", "2D", "3D", "MIXED_2D", "MIXED_3D"}


class GenerativeUiModeEvalDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    def test_dataset_has_five_fixed_distinct_requests_and_expected_modes(self):
        dataset = self.dataset
        self.assertEqual(dataset["dataset_id"], "generative_ui_mode_selection_v1")
        self.assertEqual(len(dataset["criteria"]), 5)
        self.assertEqual(len(dataset["cases"]), 5)
        cases = dataset["cases"]
        ids = [case["id"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            set(ids),
            {
                "compare_two_options",
                "loan_payment_scenarios",
                "system_request_flow",
                "rotatable_three_dimensional_model",
                "text_only_options",
            },
        )

        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertRegex(case["id"], r"^[a-z][a-z0-9_]+$")
                self.assertTrue(case["rationale"].strip())
                self.assertEqual(case["messages"][-1]["role"], "user")
                self.assertTrue(all(message["role"] in {"user", "assistant"} for message in case["messages"]))
                self.assertTrue(all(message["content"].strip() for message in case["messages"]))
                expect = case["expect"]
                self.assertIn(expect["baseline_ui_mode"], LEGACY_MODES)
                self.assertIn(expect["ui_mode"], CURRENT_MODES)
                self.assertIsInstance(expect["ui_skill_selected"], bool)
                self.assertIsInstance(expect["explicit_text_only"], bool)
                self.assertEqual(expect["ui_skill_selected"], expect["ui_mode"] != "NONE")

    def test_cases_cover_each_targeted_selection_boundary(self):
        cases = {case["id"]: case for case in self.dataset["cases"]}
        self.assertEqual(cases["compare_two_options"]["expect"]["ui_mode"], "STRUCTURED_UI")
        self.assertEqual(cases["loan_payment_scenarios"]["expect"]["ui_mode"], "STRUCTURED_UI")
        self.assertEqual(cases["system_request_flow"]["expect"]["ui_mode"], "STRUCTURED_UI")
        self.assertEqual(cases["rotatable_three_dimensional_model"]["expect"]["ui_mode"], "3D")
        self.assertEqual(cases["text_only_options"]["expect"]["ui_mode"], "NONE")
        self.assertTrue(cases["text_only_options"]["expect"]["explicit_text_only"])


if __name__ == "__main__":
    unittest.main()
