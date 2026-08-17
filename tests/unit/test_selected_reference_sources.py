import unittest
from unittest.mock import Mock

from services.selected_reference_sources import (
    DeduplicatedLookup,
    build_selected_reference_searchers,
)


class DeduplicatedLookupTestCase(unittest.TestCase):
    # 日本語: 同じクエリを二度引かず、事前検索済みの本文をコンテキストへ二重に積みません。
    # English: The same query is not run twice, so prefetched bodies are never stacked twice.
    def test_repeated_query_is_not_forwarded(self):
        search = Mock(return_value={"status": "ok", "prompt_count": 1})
        lookup = DeduplicatedLookup(search, source_label="shared prompt")

        first = lookup("議事録 テンプレ")
        second = lookup("  議事録   テンプレ  ")

        search.assert_called_once_with("議事録 テンプレ")
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "already_searched")

    # 日本語: 別のキーワードは通常どおり検索します。
    # English: A materially different query is forwarded as usual.
    def test_new_query_is_forwarded(self):
        search = Mock(return_value={"status": "ok"})
        lookup = DeduplicatedLookup(search, source_label="shared prompt")

        lookup("議事録")
        lookup("週報")

        self.assertEqual([item.args[0] for item in search.call_args_list], ["議事録", "週報"])

    # 日本語: 失敗したクエリは記録しません。記録すると障害からの引き直しが空振りします。
    # English: A failed query is not recorded, otherwise the retry after an outage would no-op.
    def test_failed_query_can_be_retried(self):
        search = Mock(side_effect=[{"status": "failed"}, {"status": "ok"}])
        lookup = DeduplicatedLookup(search, source_label="shared prompt")

        lookup("議事録")
        second = lookup("議事録")

        self.assertEqual(search.call_count, 2)
        self.assertEqual(second["status"], "ok")

    # 日本語: 例外で落ちたクエリも記録せず、引き直しを潰しません。
    # English: A raising query is not recorded either, so the retry still reaches the search.
    def test_raising_query_can_be_retried(self):
        search = Mock(side_effect=[RuntimeError("boom"), {"status": "ok"}])
        lookup = DeduplicatedLookup(search, source_label="shared prompt")

        with self.assertRaises(RuntimeError):
            lookup("議事録")
        second = lookup("議事録")

        self.assertEqual(search.call_count, 2)
        self.assertEqual(second["status"], "ok")


class BuildSelectedReferenceSearchersTestCase(unittest.TestCase):
    def _build(self, **kwargs):
        defaults = {
            "user_id": 42,
            "use_personal_knowledge": False,
            "use_shared_prompts": False,
            "search_personal_knowledge": Mock(return_value={"status": "ok"}),
            "search_shared_prompts": Mock(return_value={"status": "ok"}),
        }
        return build_selected_reference_searchers(**{**defaults, **kwargs})

    # 日本語: フラグが無ければ、どの参照元も生成へ渡しません。
    # English: Without the flags, no reference source reaches generation.
    def test_no_flag_wires_up_nothing(self):
        searchers = self._build()

        self.assertIsNone(searchers.personal_knowledge)
        self.assertIsNone(searchers.shared_prompt)
        self.assertEqual(searchers.unavailable_sources, ())

    # 日本語: メモ参照はユーザーIDに束ねて渡します。
    # English: The memo lookup is bound to the owning user id.
    def test_personal_knowledge_is_bound_to_the_user(self):
        search = Mock(return_value={"status": "ok"})

        searchers = self._build(use_personal_knowledge=True, search_personal_knowledge=search)
        searchers.personal_knowledge("沖縄")

        search.assert_called_once_with(42, "沖縄")
        self.assertEqual(searchers.unavailable_sources, ())

    # 日本語: 未ログインではメモを読めないため、無効化した事実を持ち回ります。
    # English: A signed-out session cannot read memos, so the dropped source is carried back.
    def test_guest_memo_request_is_reported_as_unavailable(self):
        searchers = self._build(user_id=None, use_personal_knowledge=True)

        self.assertIsNone(searchers.personal_knowledge)
        self.assertEqual(searchers.unavailable_sources, ("personal_knowledge_search",))

    # 日本語: 共有プロンプトは公開データなので、ゲストでも利用できます。
    # English: Shared prompts are public, so guests keep the lookup.
    def test_guest_keeps_the_shared_prompt_lookup(self):
        searchers = self._build(user_id=None, use_shared_prompts=True)

        self.assertIsNotNone(searchers.shared_prompt)
        self.assertEqual(searchers.unavailable_sources, ())


if __name__ == "__main__":
    unittest.main()
