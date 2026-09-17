import json
import unittest
from concurrent.futures import Future
from unittest.mock import Mock, patch

from services.chat_evidence_store import EvidenceStore
from services.chat_web_page_reader import MAX_PAGE_LENGTH, WebPageReader
from services.url_fetcher import MAX_URL_TEXT_CHARS, FetchedUrlDocument
from services.web_search import WebSearchResult, WebSearchSource


class WebPageReaderTestCase(unittest.TestCase):
    def setUp(self):
        self.store = EvidenceStore()
        self.source = self.add_source("https://example.com/article")
        self.reader = WebPageReader(self.store)

    def add_source(self, url):
        source = WebSearchSource(url=url, title="Article", hostname="example.com", age="", snippets=("Saved snippet",))
        self.store.add_web_result(WebSearchResult(query="query", searched_at="2026-09-09", freshness="", sources=(source,)))
        return source

    def document(self, text="Opening.\nDetails.\nExceptions."):
        return FetchedUrlDocument(
            requested_url=self.source.url,
            final_url="https://example.com/final",
            title="Current article",
            text=text,
        )

    def read(self, **kwargs):
        return self.reader.execute_read_web_page({"evidence_id": self.source.evidence_id, **kwargs})

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_known_id_fetches_once_and_later_ranges_use_same_snapshot(self, fetch):
        fetch.return_value = self.document()
        first = self.read(length=9)
        second = self.read(start=first["next_start"])
        self.assertEqual(first["text"] + second["text"], fetch.return_value.text)
        self.assertEqual(second["fetched_at"], first["fetched_at"])
        self.assertEqual(first["final_url"], "https://example.com/final")
        self.assertIsNone(second["next_start"])
        fetch.assert_called_once_with(self.source.url)
        self.assertFalse(self.store.get(self.source.evidence_id)["source"]["page_text"])

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_pagination_fits_serialized_json_with_escaping_without_losing_text(self, fetch):
        fetch.return_value = self.document('引用 " \\ \n' * 200)
        start = 0
        parts = []
        while start is not None:
            result = self.reader.execute_read_web_page(
                {"evidence_id": self.source.evidence_id, "start": start, "length": MAX_PAGE_LENGTH}, max_chars=1000,
            )
            self.assertEqual(result["status"], "ok")
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 1000)
            self.assertTrue(result["text"])
            self.assertGreater(result["end"], start)
            parts.append(result["text"])
            start = result["next_start"]
        self.assertEqual("".join(parts), "\n".join(line.strip() for line in fetch.return_value.text.splitlines()))
        fetch.assert_called_once()

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_unknown_nonweb_and_arbitrary_url_requests_never_fetch(self, fetch):
        memo_id = self.store.add_reference_payload(
            {"memos": [{"id": 1, "url": self.source.url, "content": "memo"}]}, source_type="personal_knowledge",
        )[0]["evidence_id"]
        for evidence_id in ("other-turn-id", self.source.url, memo_id):
            with self.subTest(evidence_id=evidence_id):
                result = self.reader.execute_read_web_page({"evidence_id": evidence_id})
                self.assertEqual(result["status"], "not_found")
        result = self.reader.execute_read_web_page({"evidence_id": self.source.evidence_id, "url": "http://localhost"})
        self.assertEqual(result["status"], "invalid_arguments")
        fetch.assert_not_called()

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_invalid_arguments_are_payloads_and_do_not_fetch(self, fetch):
        bad_arguments = [
            "{", "[]", None, {}, {"evidence_id": ["id"]},
            {"evidence_id": "x", "start": True}, {"evidence_id": "x", "start": -1},
            {"evidence_id": "x", "length": 0}, {"evidence_id": "x", "length": MAX_PAGE_LENGTH + 1},
        ]
        for arguments in bad_arguments:
            with self.subTest(arguments=arguments):
                self.assertEqual(self.reader.execute_read_web_page(arguments)["status"], "invalid_arguments")
        fetch.assert_not_called()

    @patch("services.chat_web_page_reader.fetch_url_document", return_value=None)
    def test_failed_url_is_not_retried(self, fetch):
        self.assertEqual(self.read()["status"], "fetch_failed")
        self.assertEqual(self.read()["status"], "fetch_failed")
        fetch.assert_called_once()

    @patch("services.chat_web_page_reader.fetch_url_document", side_effect=RuntimeError("provider failure"))
    def test_unexpected_failure_is_cached_without_exposing_exception(self, fetch):
        result = self.read()
        self.assertEqual(result["status"], "fetch_failed")
        self.assertNotIn("provider failure", json.dumps(result))
        self.read()
        fetch.assert_called_once()

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_page_limit_includes_failed_requests_and_allows_cached_reads(self, fetch):
        fetch.side_effect = [self.document(), None, self.document()]
        self.read()
        for index in range(1, 4):
            source = self.add_source(f"https://example.com/{index}")
            result = self.reader.execute_read_web_page({"evidence_id": source.evidence_id})
        self.assertEqual(result["status"], "fetch_budget_exhausted")
        self.assertEqual(self.read()["status"], "ok")
        self.assertEqual(fetch.call_count, 3)

    @patch("services.chat_web_page_reader.ThreadPoolExecutor")
    def test_timeout_is_cached_and_prevents_further_external_fetches(self, executor_class):
        self.reader = WebPageReader(self.store, max_fetch_seconds=0.1)
        executor = executor_class.return_value
        executor.submit.return_value = Mock(spec=Future)
        executor.submit.return_value.result.side_effect = TimeoutError
        self.assertEqual(self.read()["status"], "fetch_timeout")
        self.assertEqual(self.read()["status"], "fetch_timeout")
        other = self.add_source("https://example.com/other")
        result = self.reader.execute_read_web_page({"evidence_id": other.evidence_id})
        self.assertEqual(result["status"], "fetch_budget_exhausted")
        executor.submit.assert_called_once()
        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)

    @patch("services.chat_web_page_reader.ThreadPoolExecutor")
    def test_per_page_timeout_preserves_remaining_budget_for_another_page(self, executor_class):
        executor = executor_class.return_value
        slow_future = Mock(spec=Future)
        slow_future.result.side_effect = TimeoutError
        safe_future = Mock(spec=Future)
        safe_future.result.return_value = self.document()
        executor.submit.side_effect = [slow_future, safe_future]

        self.assertEqual(self.read()["status"], "fetch_timeout")
        other = self.add_source("https://example.com/other")
        result = self.reader.execute_read_web_page({"evidence_id": other.evidence_id})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(executor.submit.call_count, 2)
        self.assertEqual(slow_future.result.call_args.kwargs["timeout"], 10)

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_text_extraction_limit_and_invalid_range_are_explicit(self, fetch):
        fetch.return_value = self.document("x" * (MAX_URL_TEXT_CHARS + 10))
        result = self.read(start=MAX_URL_TEXT_CHARS - 4)
        self.assertEqual(result["text"], "xxxx")
        self.assertTrue(result["text_limit_reached"])
        self.assertEqual(result["total_chars"], MAX_URL_TEXT_CHARS)
        self.assertIn("incomplete", result["usage_note"])
        self.assertEqual(self.read(start=MAX_URL_TEXT_CHARS)["status"], "range_not_found")

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_insufficient_response_budget_never_starts_fetch(self, fetch):
        result = self.reader.execute_read_web_page({"evidence_id": self.source.evidence_id}, max_chars=100)
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 100)
        fetch.assert_not_called()

    @patch("services.url_fetcher.requests.Session.get")
    @patch("services.url_fetcher._resolve_safe_ip", return_value=None)
    def test_saved_unsafe_url_still_passes_through_existing_ssrf_guard(self, resolve, request):
        source = self.add_source("http://127.0.0.1/private")
        result = self.reader.execute_read_web_page({"evidence_id": source.evidence_id})
        self.assertEqual(result["status"], "fetch_failed")
        resolve.assert_called_once_with(source.url)
        request.assert_not_called()

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_nonstandard_port_evidence_never_starts_fetch(self, fetch):
        source = self.add_source("https://example.com:8443/private")
        result = self.reader.execute_read_web_page({"evidence_id": source.evidence_id})
        self.assertEqual(result["status"], "fetch_failed")
        fetch.assert_not_called()


# チャット欄に貼られたURLは取得済み本文を種として渡され、再取得なしで分割読み取りできる。
# A URL pasted into the chat seeds its already-fetched body, so chunked reads never refetch.
class SeededPastedPageTestCase(unittest.TestCase):
    def setUp(self):
        self.store = EvidenceStore()
        self.url = "https://example.com/long"
        self.text = "".join(f"行{index}\n" for index in range(1, 2001))
        self.reference = self.store.add_pasted_page(
            url=self.url,
            title="長い記事",
            snippet=self.text[:50],
            fetched_at="2026-09-18T00:00:00+00:00",
        )
        self.reader = WebPageReader(self.store)
        self.reader.seed_page(
            self.url,
            text=self.text,
            title="長い記事",
            fetched_at="2026-09-18T00:00:00+00:00",
        )

    def read(self, **kwargs):
        return self.reader.execute_read_web_page(
            {"evidence_id": self.reference["evidence_id"], **kwargs}
        )

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_seeded_page_is_read_without_fetching(self, fetch):
        result = self.read(length=100)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["text"], self.text[:100])
        self.assertEqual(result["total_chars"], len(self.text))
        self.assertEqual(result["fetched_at"], "2026-09-18T00:00:00+00:00")
        fetch.assert_not_called()

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_chunked_reads_cover_the_whole_body(self, fetch):
        collected = ""
        start = 0
        for _ in range(40):
            chunk = self.read(start=start, length=MAX_PAGE_LENGTH)
            self.assertEqual(chunk["status"], "ok")
            collected += chunk["text"]
            if chunk["next_start"] is None:
                break
            start = chunk["next_start"]
        self.assertEqual(collected, self.text)
        fetch.assert_not_called()

    @patch("services.chat_web_page_reader.fetch_url_document")
    def test_reading_after_an_inlined_excerpt_resumes_without_a_gap(self, fetch):
        # 発話へ前置した抜粋の直後（= その文字数）から続きを読めることを確かめる。
        # The read resumes exactly where the excerpt prepended to the message stopped.
        excerpt = self.text[:3_000]
        result = self.read(start=len(excerpt), length=1_000)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(excerpt + result["text"], self.text[: len(excerpt) + len(result["text"])])
        fetch.assert_not_called()

    def test_seed_never_replaces_a_page_already_in_the_cache(self):
        self.assertFalse(self.reader.seed_page(self.url, text="別の本文"))
        self.assertEqual(self.read(length=10)["text"], self.text[:10])

    def test_seed_rejects_unusable_input(self):
        self.assertFalse(self.reader.seed_page("ftp://example.com/x", text="本文"))
        self.assertFalse(self.reader.seed_page("https://example.com/empty", text=""))


if __name__ == "__main__":
    unittest.main()
