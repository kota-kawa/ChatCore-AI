import unittest
from datetime import datetime
from unittest.mock import patch

from services.reference_query_rewrite import (
    MAX_REWRITTEN_QUERIES,
    rewrite_reference_query,
)


class RewriteReferenceQueryTestCase(unittest.TestCase):
    def _rewrite(self, raw, **kwargs):
        with patch(
            "services.reference_query_rewrite.get_llm_json_response", return_value=raw
        ) as call:
            return rewrite_reference_query("今月は何をしたらいいかな？", **kwargs), call

    def test_returns_the_keyword_queries(self):
        queries, _ = self._rewrite('{"queries": ["2026年8月 8月 目標", "今月 予定 タスク"]}')

        self.assertEqual(queries, ["2026年8月 8月 目標", "今月 予定 タスク"])

    def test_todays_date_and_previous_turn_reach_the_model(self):
        _, call = self._rewrite(
            '{"queries": ["8月 目標"]}',
            previous_query="来月の予定を立てたい",
            now=datetime(2026, 8, 18),
        )

        prompt = call.call_args.args[0][1]["content"]
        self.assertIn("2026-08-18", prompt)
        self.assertIn("来月の予定を立てたい", prompt)

    def test_caps_the_number_of_queries(self):
        queries, _ = self._rewrite('{"queries": ["a", "b", "c", "d"]}')

        self.assertEqual(len(queries), MAX_REWRITTEN_QUERIES)

    def test_json_wrapped_in_prose_is_still_parsed(self):
        queries, _ = self._rewrite('Here you go: {"queries": ["8月 目標"]} — hope that helps')

        self.assertEqual(queries, ["8月 目標"])

    def test_unusable_replies_yield_no_queries(self):
        for raw in ("", "not json", '{"queries": []}', '{"queries": [1, null]}', "[]"):
            with self.subTest(raw=raw):
                queries, _ = self._rewrite(raw)
                self.assertEqual(queries, [])

    def test_a_query_identical_to_the_turn_is_dropped(self):
        queries, _ = self._rewrite('{"queries": ["今月は何をしたらいいかな？", "8月 目標"]}')

        self.assertEqual(queries, ["8月 目標"])

    def test_provider_failure_is_not_raised_to_the_caller(self):
        with patch(
            "services.reference_query_rewrite.get_llm_json_response",
            side_effect=RuntimeError("provider down"),
        ):
            self.assertEqual(rewrite_reference_query("今月は何をしたらいいかな？"), [])

    def test_blank_input_skips_the_model_entirely(self):
        with patch("services.reference_query_rewrite.get_llm_json_response") as call:
            self.assertEqual(rewrite_reference_query("   "), [])

        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
