import json
import re
import unittest
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

DATASET_PATH = Path(__file__).resolve().parents[1] / "fixtures/llm_eval/chat_followup_new_information_cases_v1.json"
# 保存済みの根拠だけで答えられる追質問。検索は要らないが、前のターンの出典は持つ。
# A follow-up answerable from stored evidence: no new search, but it carries the earlier sources.
STORED_EVIDENCE_CASE_ID = "followup_evidence_already_sufficient_web"


class ChatFollowupNewInformationEvalDatasetTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    def test_cases_end_with_a_follow_up_and_state_what_is_new(self):
        dataset = self.dataset
        self.assertEqual(dataset["dataset_id"], "chat_followup_new_information_v1")
        self.assertTrue(dataset["criteria"])
        self.assertIsNotNone(datetime.fromisoformat(dataset["current_time"]).tzinfo)
        cases = dataset["cases"]
        ids = [case["id"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            [case["id"] for case in cases if case["expect"]["repetition_expected"]],
            ["explicit_repeat_requested"],
        )
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertRegex(case["id"], r"^[a-z][a-z0-9_]+$")
                self.assertTrue(case["rationale"].strip())
                roles = [message["role"] for message in case["messages"]]
                self.assertGreaterEqual(len(roles), 3)
                self.assertEqual(roles, ["user", "assistant"] * (len(roles) // 2) + ["user"])
                for message in case["messages"]:
                    self.assertTrue(message["content"].strip())
                    self.assertNotIn("[[source:", message["content"])
                expect = case["expect"]
                for key in ("required_content", "avoid"):
                    self.assertTrue(2 <= len(expect[key]) <= 4)
                    self.assertTrue(all(isinstance(item, str) and item.strip() for item in expect[key]))
                for key in ("repetition_expected", "web_required"):
                    self.assertIsInstance(expect[key], bool)

    def test_prior_and_fresh_searches_reference_disjoint_existing_sources(self):
        for case in self.dataset["cases"]:
            with self.subTest(case=case["id"]):
                labels = [source["label"] for source in case["sources"]]
                self.assertEqual(len(labels), len(set(labels)))
                prior = case["prior_search"]
                prior_labels = prior["source_labels"] if prior else []
                fresh_labels = case["fresh_search_source_labels"]
                self.assertFalse(set(prior_labels) & set(fresh_labels))
                self.assertEqual(sorted([*prior_labels, *fresh_labels]), sorted(labels))
                self.assertEqual(case["expect"]["web_required"], bool(fresh_labels))
                if prior:
                    self.assertTrue(prior["query"].strip())
                    self.assertTrue(prior_labels)
                    searched_at = datetime.fromisoformat(prior["searched_at"])
                    self.assertLessEqual(searched_at, datetime.fromisoformat(self.dataset["current_time"]))
                    published = {source["label"]: date.fromisoformat(source["published"]) for source in case["sources"]}
                    for label in prior_labels:
                        self.assertLessEqual(published[label], searched_at.date())
                if not fresh_labels and case["id"] != STORED_EVIDENCE_CASE_ID:
                    self.assertEqual(case["sources"], [])
                    self.assertIsNone(prior)

    def test_sources_are_synthetic_and_available_at_the_fixed_time(self):
        current_date = datetime.fromisoformat(self.dataset["current_time"]).date()
        urls = []
        for case in self.dataset["cases"]:
            for source in case["sources"]:
                with self.subTest(case=case["id"], source=source["label"]):
                    for key in ("label", "title", "url", "published", "snippet", "page_excerpt"):
                        self.assertTrue(source[key].strip())
                    parsed = urlsplit(source["url"])
                    self.assertEqual(parsed.scheme, "https")
                    self.assertEqual(parsed.hostname, "example.com")
                    published = date.fromisoformat(source["published"])
                    self.assertLessEqual(published, current_date)
                    for year, month, day in re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", source["page_excerpt"]):
                        self.assertLessEqual(date(int(year), int(month), int(day)), published)
                    self.assertNotIn("[[source:", json.dumps(source))
                    urls.append(source["url"])
        self.assertEqual(len(urls), len(set(urls)))


if __name__ == "__main__":
    unittest.main()
