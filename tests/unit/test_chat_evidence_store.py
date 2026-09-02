import json
import unittest

from services.chat_evidence_store import (
    GET_EVIDENCE_TOOL_NAME,
    MAX_EVIDENCE_IDS_PER_CALL,
    EvidenceRequestError,
    EvidenceStore,
    get_evidence_tool_definition,
)
from services.web_search import WebSearchResult, WebSearchSource


class EvidenceStoreTestCase(unittest.TestCase):
    def _web_result(
        self,
        *,
        query: str = "query",
        page_text: str = "full page body",
    ) -> WebSearchResult:
        return WebSearchResult(
            query=query,
            searched_at="2026-09-02T00:00:00+00:00",
            freshness="week",
            sources=(
                WebSearchSource(
                    url="https://example.com/article",
                    title="Article",
                    hostname="example.com",
                    age="1 day ago",
                    snippets=("complete snippet",),
                    page_text=page_text,
                    link_depth=1,
                    linked_from_url="https://example.com/",
                ),
            ),
        )

    def test_web_result_keeps_full_source_and_search_context_by_existing_id(self):
        store = EvidenceStore()
        result = self._web_result()

        references = store.add_web_result(result)
        record = store.get(result.sources[0].evidence_id)

        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["evidence_id"], result.sources[0].evidence_id)
        self.assertEqual(references[0]["source_type"], "web")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["query"], "query")
        self.assertEqual(record["searched_at"], "2026-09-02T00:00:00+00:00")
        self.assertEqual(record["freshness"], "week")
        self.assertEqual(record["source"]["page_text"], "full page body")
        self.assertEqual(record["source"]["snippets"], ("complete snippet",))

    def test_repeated_web_source_retains_richest_body_and_all_search_contexts(self):
        store = EvidenceStore()
        store.add_web_result(self._web_result(query="first", page_text="rich body"))
        second = self._web_result(query="second", page_text="x")

        store.add_web_result(second)
        record = store.get(second.sources[0].evidence_id)

        assert record is not None
        self.assertEqual(record["source"]["page_text"], "rich body")
        self.assertEqual(
            [context["query"] for context in record["search_contexts"]],
            ["first", "second"],
        )

    def test_reference_items_receive_stable_ids_without_mutating_input(self):
        payload = {
            "status": "ok",
            "query": "旅行",
            "memo_count": 1,
            "usage_note": "reference data",
            "memos": [
                {
                    "id": 42,
                    "title": "旅行メモ",
                    "content": "全文を保持する。" * 200,
                    "collection": "plans",
                }
            ],
        }
        store = EvidenceStore()

        first = store.add_reference_payload(payload, source_type="personal_knowledge")
        second = store.add_reference_payload(payload, source_type="personal_knowledge")

        self.assertEqual(first[0]["evidence_id"], second[0]["evidence_id"])
        self.assertTrue(first[0]["evidence_id"].startswith("ref_"))
        self.assertNotIn("evidence_id", payload["memos"][0])
        record = store.get(first[0]["evidence_id"])
        assert record is not None
        self.assertEqual(record["item"]["content"], "全文を保持する。" * 200)
        self.assertEqual(record["item"]["evidence_id"], first[0]["evidence_id"])
        self.assertEqual(record["payload_metadata"]["status"], "ok")
        self.assertEqual(record["payload_metadata"]["memo_count"], 1)

    def test_reference_id_does_not_depend_on_item_order(self):
        items = [
            {"prompt_id": "p1", "title": "One", "content": "first"},
            {"prompt_id": "p2", "title": "Two", "content": "second"},
        ]
        first_store = EvidenceStore()
        second_store = EvidenceStore()

        first = first_store.add_reference_payload(
            {"query": "q", "prompts": items},
            source_type="shared_prompt",
        )
        second = second_store.add_reference_payload(
            {"query": "q", "prompts": list(reversed(items))},
            source_type="shared_prompt",
        )

        first_by_title = {item["title"]: item["evidence_id"] for item in first}
        second_by_title = {item["title"]: item["evidence_id"] for item in second}
        self.assertEqual(first_by_title, second_by_title)

    def test_get_many_is_bounded_and_returns_defensive_copies(self):
        store = EvidenceStore(max_ids_per_call=2)
        reference = store.add_reference_payload(
            {"memos": [{"id": "m1", "title": "Memo", "content": "body"}]},
            source_type="personal_knowledge",
        )[0]
        evidence_id = reference["evidence_id"]

        records = store.get_many([evidence_id, evidence_id, "missing"])
        records[0]["item"]["content"] = "changed"

        self.assertEqual(len(records), 1)
        self.assertEqual(store.get(evidence_id)["item"]["content"], "body")
        with self.assertRaises(EvidenceRequestError):
            store.get_many(["one", "two", "three"])
        with self.assertRaises(EvidenceRequestError):
            store.get_many(evidence_id)

    def test_execute_get_evidence_reports_partial_and_invalid_requests(self):
        store = EvidenceStore()
        reference = store.add_reference_payload(
            {"prompts": [{"prompt_id": "p1", "title": "Prompt", "content": "body"}]},
            source_type="shared_prompt",
        )[0]

        partial = store.execute_get_evidence(
            {"evidence_ids": [reference["evidence_id"], "ref_missing"]}
        )
        invalid = store.execute_get_evidence({"evidence_ids": []})
        too_many = store.execute_get_evidence(
            {"evidence_ids": [f"ref_{index}" for index in range(MAX_EVIDENCE_IDS_PER_CALL + 1)]}
        )

        self.assertEqual(partial["status"], "partial")
        self.assertEqual(len(partial["evidence"]), 1)
        self.assertEqual(partial["missing_ids"], ["ref_missing"])
        self.assertEqual(invalid["status"], "invalid_arguments")
        self.assertEqual(too_many["status"], "invalid_arguments")

    # 日本語: 再取得した根拠が予算を超える場合、IDを残したまま本文から落とし、最後は
    # レコードごと外して切り詰めを明示することを検証します。
    # English: Oversized retrievals drop bodies first and whole records last, always keeping
    # the evidence IDs and reporting the truncation explicitly.
    def test_get_evidence_fits_the_caller_evidence_budget(self):
        store = EvidenceStore()
        first = store.add_web_result(
            self._web_result(query="first", page_text="a" * 4000)
        )[0]
        second = store.add_web_result(
            WebSearchResult(
                query="second",
                searched_at="2026-09-02T00:00:00+00:00",
                sources=(
                    WebSearchSource(
                        url="https://example.com/other",
                        title="Other",
                        hostname="example.com",
                        age="",
                        snippets=("b" * 4000,),
                        page_text="c" * 4000,
                    ),
                ),
            )
        )[0]
        requested = [first["evidence_id"], second["evidence_id"]]

        payload = store.execute_get_evidence(
            {"evidence_ids": requested},
            max_chars=1200,
        )
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertLessEqual(len(serialized), 1200)
        self.assertEqual(payload["status"], "evidence_truncated")
        self.assertIn("evidence budget", payload["message"])
        kept_ids = [record["evidence_id"] for record in payload["evidence"]]
        self.assertEqual(kept_ids + payload.get("truncated_ids", []), requested)
        # 予算内なら本文まで含めてそのまま返す。
        # A retrieval that fits its budget keeps the complete bodies.
        untouched = store.execute_get_evidence({"evidence_ids": requested}, max_chars=0)
        self.assertEqual(untouched["status"], "ok")
        self.assertEqual(untouched["evidence"][0]["source"]["page_text"], "a" * 4000)

    def test_get_evidence_tool_definition_uses_bounded_array_argument(self):
        definition = get_evidence_tool_definition()

        function = definition["function"]
        self.assertEqual(function["name"], GET_EVIDENCE_TOOL_NAME)
        evidence_ids = function["parameters"]["properties"]["evidence_ids"]
        self.assertEqual(evidence_ids["type"], "array")
        self.assertEqual(evidence_ids["items"]["type"], "string")
        self.assertIn(str(MAX_EVIDENCE_IDS_PER_CALL), evidence_ids["description"])


if __name__ == "__main__":
    unittest.main()
