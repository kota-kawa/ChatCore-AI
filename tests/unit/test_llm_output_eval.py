import json
import tempfile
import unittest
from pathlib import Path

from services.generative_ui import normalize_response_with_artifacts, requested_artifact_quality_issues
from services.web_search import resolve_web_search_citations, strip_web_search_citation_html
from tests.helpers.llm_eval import DATASET_PATH, EvalDatasetError, load_dataset


class LlmOutputEvalDatasetTestCase(unittest.TestCase):
    """
    固定したデータセットが、使う前の機械的な検証を通ることを確認するテストケースクラス
    Test case class verifying the frozen dataset passes its mechanical validation before use.
    """

    def test_dataset_loads_and_passes_validation(self):
        """
        データセットが読み込め、ケースIDの重複や参照切れが無いことを検証します。
        Verify the dataset loads with no duplicate case ids and no dangling references.
        """
        citation_cases, artifact_cases = load_dataset()

        self.assertTrue(citation_cases, "引用ケースが1件も無い / no citation cases")
        self.assertTrue(artifact_cases, "生成UIケースが1件も無い / no artifact cases")

        case_ids = [case.case_id for case in citation_cases] + [case.case_id for case in artifact_cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_dataset_validation_rejects_a_dangling_reference(self):
        """
        期待値が存在しない出典を指している壊れたデータを、検証が弾くことを確認します。
        Verify validation rejects a case whose expectation points at a source that does not exist.
        """
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["citation_cases"][0]["expect"]["citation_labels"] = ["not_a_source"]

        self._assert_rejected(broken)

    def test_dataset_validation_rejects_unaccounted_markers(self):
        """
        本文の marker 数と期待値が食い違うデータを、検証が弾くことを確認します。
        Verify validation rejects a case whose expectations do not account for every marker.
        """
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["citation_cases"][0]["expect"]["citation_labels"] = ["price_notice"]

        self._assert_rejected(broken)

    def test_dataset_validation_rejects_a_valid_artifact_without_gate_expectations(self):
        """
        品質ゲートの期待を書かずに済ませた生成UIケースを、検証が弾くことを確認します。
        Verify validation rejects a requested, valid artifact case that omits its gate expectations.
        """
        broken = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        broken["artifact_cases"][0]["expect"]["quality_issue_labels"] = None

        self._assert_rejected(broken)

    def _assert_rejected(self, dataset: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(EvalDatasetError):
                load_dataset(path)


class LlmOutputEvalTestCase(unittest.TestCase):
    """
    固定入力に対するチャット出力の扱いが、決定的な観点で変わっていないことを検証するテストケースクラス
    Test case class verifying deterministic chat-output handling stays unchanged for frozen inputs.
    """

    @classmethod
    def setUpClass(cls):
        cls.citation_cases, cls.artifact_cases = load_dataset()

    def test_citations_resolve_only_to_sources_present_in_the_input(self):
        """
        引用が入力の検索結果だけに解決され、存在しない根拠IDが本文に残らないことを検証します。
        Verify citations resolve only to sources in the input and unknown evidence ids never remain.
        """
        for case in self.citation_cases:
            with self.subTest(case=case.case_id):
                resolution = resolve_web_search_citations(case.model_output, case.result)

                self.assertEqual(
                    [citation.evidence_id for citation in resolution.citations],
                    case.expected_evidence_ids(),
                )
                self.assertEqual(list(resolution.invalid_markers), case.expect["invalid_markers"])

    def test_answer_prose_survives_citation_rendering(self):
        """
        引用を描画した後も、本文が marker の位置以外は変わらずに残ることを検証します。
        Verify the prose around the markers survives citation rendering unchanged.
        """
        for case in self.citation_cases:
            with self.subTest(case=case.case_id):
                resolution = resolve_web_search_citations(case.model_output, case.result)

                self.assertEqual(strip_web_search_citation_html(resolution.text), case.expect["plain_text"])

    def test_each_citation_points_at_the_source_it_cites(self):
        """
        出典チップのURLと表題が、その marker が指す検索結果と一致することを検証します。
        Verify every rendered citation carries the URL and title of the source its marker names.
        """
        for case in self.citation_cases:
            with self.subTest(case=case.case_id):
                resolution = resolve_web_search_citations(case.model_output, case.result)
                by_evidence_id = {source.evidence_id: source for source in case.result.sources}

                ordinals = {
                    source.evidence_id: index
                    for index, source in enumerate(case.result.sources, start=1)
                }

                for citation in resolution.citations:
                    source = by_evidence_id[citation.evidence_id]
                    self.assertEqual(citation.url, source.url)
                    self.assertEqual(citation.title, source.title)
                    self.assertEqual(citation.ordinal, ordinals[citation.evidence_id])
                    self.assertIn(citation.url, resolution.text)

    def test_generated_ui_outcome_matches_the_recorded_expectation(self):
        """
        生成UIの状態・理由コード・品質ゲートの指摘が、固定した期待値と一致することを検証します。
        Verify the artifact status, reason codes, and gate findings match the frozen expectations.
        """
        for case in self.artifact_cases:
            with self.subTest(case=case.case_id):
                normalized = normalize_response_with_artifacts(
                    case.model_output,
                    ui_mode=case.ui_mode,
                    explicit_ui_opt_out=case.explicit_ui_opt_out,
                )

                self.assertEqual(normalized.artifact_status, case.expect["artifact_status"])
                self.assertEqual(normalized.artifact_reason_codes, case.expect["reason_codes"])

                expected_issues = case.expect["quality_issue_labels"]
                if expected_issues is not None:
                    issues = requested_artifact_quality_issues(normalized, case.ui_mode)
                    self.assertEqual(issues, expected_issues)


if __name__ == "__main__":
    unittest.main()
