"""補助モデル(画像選択・文脈抽出)の評価用データセットの形式を検証する単体テスト。
ケース ID の一意性、評価対象モデルの範囲、合成 URL のみの使用、期待値が候補・ユーザー発話と矛盾しないことを確かめる。

Unit tests for the shape of the auxiliary-model evaluation dataset (image selection and context extraction).
Checks unique case ids, the evaluated-model scope, synthetic-only URLs, and that expectations agree with the candidates and the user
message.
"""

import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from services.web_search import WebSearchResult, WebSearchSource
from services.web_search_images import WebSearchImageCandidate, _candidate_rows

# 日本語: 評価データ(JSON)の場所。tests/fixtures/llm_eval にある。
# English: Location of the evaluation data (JSON) under tests/fixtures/llm_eval.
DATASET_PATH = Path(__file__).resolve().parents[1] / "fixtures/llm_eval/auxiliary_model_selection_cases.json"


class AuxiliaryModelEvalDatasetTestCase(unittest.TestCase):
    """データセットを一度だけ読み込み、各ケースの自己整合性を機械的に検証する。LLM は呼ばない。

    Loads the dataset once and mechanically checks each case for internal consistency; no LLM is called.
    """

    @classmethod
    def setUpClass(cls):
        cls.dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    def test_cases_have_unique_ids_and_expected_group_sizes(self):
        image_cases = self.dataset["web_image_selection"]["cases"]
        context_cases = self.dataset["context_extraction"]["cases"]
        self.assertEqual(len(image_cases), 5)
        self.assertEqual(len(context_cases), 5)

        case_ids = [case["case_id"] for case in image_cases + context_cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_model_scope_excludes_claude_while_it_is_not_offered(self):
        scope = self.dataset["evaluation_scope"]
        self.assertEqual(
            scope["image_selection_baselines"],
            ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "gpt-6-luna"],
        )
        self.assertEqual(scope["target_model"], "openai/gpt-oss-20b")
        self.assertEqual(scope["excluded_model"], "claude-haiku-4-5-20251001")
        self.assertIn("not currently offered", scope["exclusion_reason"])
        self.assertNotIn(scope["excluded_model"], scope["image_selection_baselines"])

    # 日本語: 実在サイトへ誤ってアクセスしないよう、フィクスチャの URL が https の example.invalid 配下であることを確かめる。
    # English: Assert that a fixture URL is https under example.invalid, so no real site can be hit by mistake.
    def _assert_fixture_url(self, url):
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        self.assertEqual(parsed.scheme, "https")
        self.assertTrue(
            hostname == "example.invalid" or hostname.endswith(".example.invalid"),
            msg=f"Expected a synthetic fixture host, got {hostname!r}.",
        )

    def test_image_expectations_resolve_to_candidates_that_reach_the_selector(self):
        for case in self.dataset["web_image_selection"]["cases"]:
            with self.subTest(case_id=case["case_id"]):
                sources = []
                label_to_url = {}
                for source in case["sources"]:
                    candidates = []
                    self._assert_fixture_url(source["url"])
                    for image in source["images"]:
                        self._assert_fixture_url(image["url"])
                        label_to_url[image["label"]] = image["url"]
                        candidates.append(
                            WebSearchImageCandidate(
                                url=image["url"],
                                title=image["title"],
                                alt=image["alt"],
                                kind=image["kind"],
                            )
                        )
                    sources.append(
                        WebSearchSource(
                            url=source["url"],
                            title=source["title"],
                            hostname="fixture.example.invalid",
                            age="",
                            snippets=(),
                            image_candidates=tuple(candidates),
                        )
                    )

                result = WebSearchResult(
                    query=case["query"],
                    searched_at="2026-01-01T00:00:00+00:00",
                    sources=tuple(sources),
                )
                selectable_urls = {row["url"] for row in _candidate_rows(result)}
                expected = case["expected"]
                labels = expected["allowed_candidate_labels"] + expected["prohibited_candidate_labels"]
                self.assertTrue(set(labels) <= set(label_to_url))
                self.assertTrue(
                    all(label_to_url[label] in selectable_urls for label in expected["allowed_candidate_labels"])
                )
                self.assertEqual(expected["should_display"], bool(expected["allowed_candidate_labels"]))

    def test_required_context_evidence_is_verbatim_in_the_user_message(self):
        for case in self.dataset["context_extraction"]["cases"]:
            with self.subTest(case_id=case["case_id"]):
                expected = case["expected"]
                self.assertEqual(expected["candidate_presence"], bool(expected["acceptable_facts"]))
                for evidence in expected["required_evidence_substrings"]:
                    self.assertIn(evidence, case["user_message"])


if __name__ == "__main__":
    unittest.main()
