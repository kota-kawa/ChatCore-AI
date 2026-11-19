"""回答の実行記録（「回答までのステップ」）の契約 (services.answer_trace) のテスト。
保存前・読み出し後の正規化と、回答パーツへの組み込みを検証する。

Tests for the contract of the answer's execution record (services.answer_trace): the normalization applied
before storing and after reading, and how the record is added to the answer parts.
"""

import unittest

from services.answer_trace import (
    MAX_ANSWER_TRACE_STEP_SOURCES,
    MAX_ANSWER_TRACE_STEPS,
    STEP_TITLE_MAX_CHARS,
    answer_trace_part,
    is_answer_trace_part,
    legacy_answer_trace_part,
    normalize_answer_trace,
    with_answer_trace_part,
)
from tests.helpers.answer_trace_fixtures import load_answer_trace


def _trace(*steps, summary=""):
    return {"version": 1, "summary": summary, "steps": list(steps)}


def _source(**overrides):
    return {
        "url": "https://example.com/a",
        "title": "記事",
        "hostname": "example.com",
        "favicon_url": "https://example.com/icon.png",
        "fallback_label": "E",
        "link_depth": 0,
        "linked_from": "",
        **overrides,
    }


class NormalizeAnswerTraceTestCase(unittest.TestCase):
    # 日本語: サーバーが組み立てた実行記録は、正規化しても変わらないことを検証します。
    # English: Verify a record the server built is unchanged by normalization.
    def test_a_built_record_is_already_normalized(self):
        for name in ("full", "fallback_sources", "references_only", "escaped_markup"):
            with self.subTest(name=name):
                record = load_answer_trace(name)
                self.assertEqual(normalize_answer_trace(record), record)

    # 日本語: 記録の形でないもの、対応していない版、ステップが 1 つも残らないものは記録として扱わないことを検証します。
    # English: Verify a non-record, an unsupported version and a record with no surviving step are all rejected.
    def test_rejects_what_is_not_a_record(self):
        self.assertIsNone(normalize_answer_trace(None))
        self.assertIsNone(normalize_answer_trace("<details>…</details>"))
        self.assertIsNone(normalize_answer_trace({"version": 2, "steps": [{"title": "Web検索"}]}))
        self.assertIsNone(normalize_answer_trace(_trace()))
        self.assertIsNone(normalize_answer_trace(_trace({"title": "   "}, "not a step")))

    # 日本語: 欠けた項目は既定値で埋め、未知の種類・状態は既定の値へ寄せることを検証します。
    # English: Verify missing fields get defaults and unknown kinds and statuses fall back to the default values.
    def test_fills_defaults_and_falls_back_on_unknown_kind_and_status(self):
        record = normalize_answer_trace(_trace({"title": "何かの処理", "kind": "unknown", "status": "paused"}))

        self.assertEqual(
            record["steps"],
            [
                {
                    "id": "s1",
                    "kind": "info",
                    "status": "done",
                    "title": "何かの処理",
                    "detail": "",
                    "query": "",
                    "badge": "",
                    "chips": [],
                    "sources": [],
                }
            ],
        )

    # 日本語: 実行中・失敗の状態はそのまま通すことを検証します。
    # English: Verify the running and failed statuses pass through.
    def test_keeps_running_and_failed_statuses(self):
        record = normalize_answer_trace(
            _trace({"title": "Web検索", "status": "running"}, {"title": "Web検索を試行", "status": "failed"})
        )

        self.assertEqual([step["status"] for step in record["steps"]], ["running", "failed"])

    # 日本語: ステップの ID は回答の中で一意にし、欠けている・不正・重複している ID は並び順から振り直すことを検証します。
    # English: Verify step ids are unique within the answer, with missing, malformed and duplicate ids reassigned by position.
    def test_step_ids_are_unique_and_reassigned_when_unusable(self):
        record = normalize_answer_trace(
            _trace(
                {"id": "search-1", "title": "A"},
                {"id": "search-1", "title": "B"},
                {"id": "has space", "title": "C"},
                {"title": "D"},
                {"id": "s2", "title": "E"},
            )
        )

        # 元から使える ID（search-1 と s2）はそのまま残り、振り直した ID はそれらとぶつからない。
        # Ids that were usable (search-1 and s2) stay, and the reassigned ones never collide with them.
        self.assertEqual([step["id"] for step in record["steps"]], ["search-1", "s1", "s3", "s4", "s2"])

    # 日本語: 文字数・件数の上限を超えた分を切り詰めることを検証します。
    # English: Verify anything over the length and count limits is truncated.
    def test_truncates_over_limit_text_and_lists(self):
        record = normalize_answer_trace(
            _trace(
                *(
                    {
                        "title": "題" * (STEP_TITLE_MAX_CHARS + 50),
                        "sources": [_source(url=f"https://example.com/{index}") for index in range(MAX_ANSWER_TRACE_STEP_SOURCES + 5)],
                    }
                    for _ in range(MAX_ANSWER_TRACE_STEPS + 5)
                )
            )
        )

        self.assertEqual(len(record["steps"]), MAX_ANSWER_TRACE_STEPS)
        self.assertEqual(len(record["steps"][0]["title"]), STEP_TITLE_MAX_CHARS)
        self.assertTrue(record["steps"][0]["title"].endswith("..."))
        self.assertEqual(len(record["steps"][0]["sources"]), MAX_ANSWER_TRACE_STEP_SOURCES)

    # 日本語: リンクにできない URL の出典は捨て、favicon が使えないときはサイト直下のものへ寄せることを検証します。
    # English: Verify sources whose URL cannot be linked are dropped, and an unusable favicon falls back to the site root one.
    def test_drops_unsafe_source_urls_and_resolves_the_favicon(self):
        record = normalize_answer_trace(
            _trace(
                {
                    "title": "Web検索",
                    "sources": [
                        _source(url="javascript:alert(1)"),
                        _source(url="https://user:pass@example.com/a"),
                        _source(url="ftp://example.com/a"),
                        _source(url="https://example.com/a\nhttps://evil.example"),
                        _source(url="https://safe.example/a?x=1", favicon_url="javascript:alert(1)", title="", fallback_label=""),
                    ],
                }
            )
        )

        self.assertEqual(
            record["steps"][0]["sources"],
            [
                {
                    "url": "https://safe.example/a?x=1",
                    # 題名の無い出典は URL を題名にする。
                    # A source without a title uses its URL as the title.
                    "title": "https://safe.example/a?x=1",
                    "hostname": "example.com",
                    "favicon_url": "https://safe.example/favicon.ico",
                    "fallback_label": "E",
                    "link_depth": 0,
                    "linked_from": "",
                }
            ],
        )

    # 日本語: たどった階層は 0 以上の整数に収め、整数でない値は検索結果のページ（0）として扱うことを検証します。
    # English: Verify the followed depth is clamped to a non-negative integer and a non-integer counts as a result page (0).
    def test_link_depth_is_a_bounded_integer(self):
        record = normalize_answer_trace(
            _trace(
                {
                    "title": "リンクをたどって深掘り",
                    "sources": [
                        _source(url="https://example.com/1", link_depth=-3),
                        _source(url="https://example.com/2", link_depth=500),
                        _source(url="https://example.com/3", link_depth="2"),
                        _source(url="https://example.com/4", link_depth=True),
                    ],
                }
            )
        )

        self.assertEqual([source["link_depth"] for source in record["steps"][0]["sources"]], [0, 9, 0, 0])


class AnswerTracePartTestCase(unittest.TestCase):
    def setUp(self):
        self.trace = load_answer_trace("references_only")
        self.part = {"type": "answer_trace", "trace": self.trace}

    # 日本語: 実行記録を回答パーツにすること、記録として成り立たなければパーツを作らないことを検証します。
    # English: Verify a record becomes an answer part and an invalid one produces no part.
    def test_wraps_a_valid_record_only(self):
        self.assertEqual(answer_trace_part(self.trace), self.part)
        self.assertIsNone(answer_trace_part(None))
        self.assertIsNone(answer_trace_part(_trace()))

    # 日本語: 構造化前の HTML は、空でなければ本文とは別のパーツにすることを検証します。
    # English: Verify pre-structuring markup becomes a part of its own unless it is empty.
    def test_wraps_non_empty_legacy_markup(self):
        self.assertEqual(
            legacy_answer_trace_part("<details>…</details>"),
            {"type": "legacy_answer_trace", "html": "<details>…</details>"},
        )
        self.assertIsNone(legacy_answer_trace_part("  "))
        self.assertIsNone(legacy_answer_trace_part(None))

    # 日本語: 構造化・旧形式のどちらも実行記録のパーツとして見分けることを検証します。
    # English: Verify both the structured and the legacy part are recognized as an execution record.
    def test_recognizes_both_record_part_types(self):
        self.assertTrue(is_answer_trace_part(self.part))
        self.assertTrue(is_answer_trace_part({"type": "legacy_answer_trace", "html": "<details></details>"}))
        self.assertFalse(is_answer_trace_part({"type": "text", "text": "本文"}))
        self.assertFalse(is_answer_trace_part(None))

    # 日本語: 本文だけの回答では、記録の後ろに本文のテキストパーツを置くことを検証します。
    # English: Verify a body-only answer gets its body as a text part after the record.
    def test_body_only_answer_gets_a_text_part_after_the_record(self):
        self.assertEqual(
            with_answer_trace_part(None, "本文です。", self.trace),
            [self.part, {"type": "text", "text": "本文です。"}],
        )

    # 日本語: 既にパーツを持つ回答では、その先頭に記録を足すことを検証します。
    # English: Verify an answer that already has parts gets the record in front of them.
    def test_existing_parts_get_the_record_in_front(self):
        parts = [{"type": "text", "text": "前半"}, {"type": "web_search_image", "image": {}}, {"type": "text", "text": "後半"}]

        self.assertEqual(with_answer_trace_part(parts, "前半後半", self.trace), [self.part, *parts])

    # 日本語: 記録が無ければパーツを変えず、本文も無ければ記録だけのパーツ列になることを検証します。
    # English: Verify parts are untouched without a record, and a record with no body yields the record alone.
    def test_no_record_changes_nothing_and_no_body_leaves_the_record_alone(self):
        parts = [{"type": "text", "text": "本文"}]

        self.assertIs(with_answer_trace_part(parts, "本文", None), parts)
        self.assertIsNone(with_answer_trace_part(None, "本文", None))
        self.assertEqual(with_answer_trace_part(None, "", self.trace), [self.part])
        self.assertEqual(with_answer_trace_part(None, "  \n", self.trace), [self.part])

    # 日本語: 既にある実行記録のパーツは置き換え、二重にしないことを検証します。
    # English: Verify an existing record part is replaced instead of duplicated.
    def test_an_existing_record_part_is_replaced(self):
        stale = {"type": "answer_trace", "trace": load_answer_trace("fallback_sources")}

        self.assertEqual(
            with_answer_trace_part([stale, {"type": "text", "text": "本文"}], "本文", self.trace),
            [self.part, {"type": "text", "text": "本文"}],
        )


if __name__ == "__main__":
    unittest.main()
