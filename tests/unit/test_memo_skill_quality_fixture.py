import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "llm_eval"
    / "memo_skill_quality_cases.json"
)
_MEMO_TOOLS = {"memo_list", "memo_search", "memo_read", "memo_create", "memo_append", "memo_edit"}


def _claim_fact_markers(text: str) -> set[str]:
    markers = {f"year:{year}" for year in re.findall(r"\d{4}年", text)}
    markers.update(
        f"date:{month}/{day}"
        for month, day in re.findall(r"(?:\d{4}年)?(\d{1,2})月(\d{1,2})日", text)
    )
    markers.update(f"weekday:{day}曜日" for day in re.findall(r"([月火水木金土日])曜日", text))
    markers.update(
        f"time:{time}"
        for time in re.findall(r"(?:午前|午後)\d{1,2}時(?:\d{1,2}分)?", text)
    )
    return markers


class MemoSkillQualityFixtureTestCase(unittest.TestCase):
    def test_fixture_is_well_formed_and_has_unique_cases_and_models(self):
        dataset = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(dataset["version"], 1)
        self.assertIn(dataset["locale"], {"ja", "en"})
        self.assertTrue(dataset["models"])
        self.assertEqual(len(dataset["models"]), len(set(dataset["models"])))
        self.assertTrue(dataset["history"])
        self.assertTrue(dataset["cases"])

        case_ids = [case["case_id"] for case in dataset["cases"]]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case in dataset["cases"]:
            with self.subTest(case=case.get("case_id")):
                self.assertTrue(case["request"].strip())
                self.assertTrue(case["evaluation_axes"])
                self.assertIn(case["expected"]["web_search"], {"never", "required"})
                self.assertIsInstance(case["expected"]["write_proposal"], bool)
                if "required_tool" in case["expected"]:
                    self.assertIn(case["expected"]["required_tool"], _MEMO_TOOLS)

        search_case = next(
            case for case in dataset["cases"] if case["expected"]["web_search"] == "required"
        )
        fixed_search_result = dataset["fixed_search_result"]
        self.assertTrue(fixed_search_result["searched_at"].strip())
        sources = fixed_search_result["sources"]
        self.assertTrue(sources)
        source_urls = [source["url"] for source in sources]
        self.assertEqual(len(source_urls), len(set(source_urls)))
        source_markers: list[set[str]] = []
        for source in sources:
            parsed_url = urlparse(source["url"])
            self.assertEqual(parsed_url.scheme, "https")
            self.assertIsNotNone(parsed_url.hostname)
            self.assertTrue(parsed_url.hostname.strip())
            self.assertEqual(parsed_url.hostname, source["hostname"])
            self.assertTrue(source["title"].strip())
            self.assertTrue(source["age"].strip())
            self.assertTrue(source["snippets"])
            snippets = source["snippets"]
            self.assertTrue(all(isinstance(snippet, str) and snippet.strip() for snippet in snippets))
            source_markers.append(_claim_fact_markers("\n".join(snippets)))

        claims = search_case["expected"]["claims_supported_by_result"]
        self.assertTrue(claims)
        for claim in claims:
            markers = _claim_fact_markers(claim)
            self.assertTrue(markers, claim)
            self.assertTrue(
                any(markers.issubset(markers_in_source) for markers_in_source in source_markers),
                claim,
            )


if __name__ == "__main__":
    unittest.main()
