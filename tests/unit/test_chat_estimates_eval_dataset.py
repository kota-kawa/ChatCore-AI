import json
import re
import unittest
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

DATASET_PATH = Path(__file__).resolve().parents[1] / "fixtures/llm_eval/chat_estimates_followups_cases_v1.json"


class ChatEstimatesEvalDatasetTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    def test_cases_have_complete_inputs_and_distinct_expectations(self):
        dataset = self.dataset
        self.assertEqual(dataset["dataset_id"], "chat_estimates_followups_v1")
        self.assertTrue(dataset["criteria"])
        self.assertIsNotNone(datetime.fromisoformat(dataset["current_time"]).tzinfo)
        cases = dataset["cases"]
        self.assertEqual(len(cases), 5)
        ids = [case["id"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sum(not case["expect"]["inference_expected"] for case in cases), 1)
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertRegex(case["id"], r"^[a-z][a-z0-9_]+$")
                self.assertTrue(case["rationale"].strip())
                self.assertEqual(case["messages"][-1]["role"], "user")
                for message in case["messages"]:
                    self.assertIn(message["role"], {"user", "assistant"})
                    self.assertTrue(message["content"].strip())
                expect = case["expect"]
                for key in ("required_content", "avoid"):
                    self.assertTrue(expect[key])
                    self.assertTrue(all(isinstance(item, str) and item.strip() for item in expect[key]))
                for key in ("inference_expected", "web_required"):
                    self.assertIsInstance(expect[key], bool)
                self.assertEqual(expect["web_required"], bool(case["sources"]))

    def test_sources_are_synthetic_consistent_and_available_at_the_fixed_time(self):
        current_date = datetime.fromisoformat(self.dataset["current_time"]).date()
        sources_by_url = {}
        for case in self.dataset["cases"]:
            sources = case["sources"]
            self.assertEqual(len(sources), len({source["label"] for source in sources}))
            self.assertEqual(len(sources), len({source["url"] for source in sources}))
            for source in sources:
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
                    if source["url"] in sources_by_url:
                        self.assertEqual(source, sources_by_url[source["url"]])
                    sources_by_url[source["url"]] = source
                    self.assertNotIn("[[source:", json.dumps(source))

    def test_timing_cases_share_evidence_and_historical_intervals_are_correct(self):
        cases = {case["id"]: case for case in self.dataset["cases"]}
        initial = cases["initial_public_timing_estimate"]
        followup = cases["followup_estimate_after_unannounced_date"]
        facts_only = cases["official_facts_only_no_estimate"]
        self.assertEqual(initial["sources"], followup["sources"])
        self.assertEqual(initial["sources"], facts_only["sources"])
        self.assertEqual(initial["messages"][0], followup["messages"][0])
        histories = [source for source in initial["sources"] if "間隔は" in source["page_excerpt"]]
        self.assertEqual(len(histories), 2)
        for source in histories:
            text = source["page_excerpt"]
            dates = [date(int(y), int(m), int(d)) for y, m, d in re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)]
            interval = int(re.search(r"間隔は(\d+)日", text).group(1))
            self.assertEqual((dates[1] - dates[0]).days, interval)


if __name__ == "__main__":
    unittest.main()
