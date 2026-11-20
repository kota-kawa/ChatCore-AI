"""「回答までのステップ」(services.web_search_trace) の各ステップと、回答パーツ用の構造化データのテスト。

Tests for the "steps to the answer" (services.web_search_trace): each step and the structured data built for the answer part.
"""

import json
import unittest

from services import web_search_trace as trace
from services.selected_reference_context import (
    PERSONAL_KNOWLEDGE_SOURCE,
    SHARED_PROMPT_SOURCE,
)
from services.web_search import WebSearchResult, WebSearchSource


# 日本語: 「回答までのステップ」のステップ生成と、構造化データへのまとめ方を検証するテストクラスです。
# English: Test case class covering step creation and how the steps are gathered into structured data.
class WebSearchTraceTestCase(unittest.TestCase):
    def _result(self, query, hostnames, *, freshness="", page_text=""):
        # 日本語: テスト用の検索結果を組み立てるヘルパーです。
        # English: Helper that builds a search result for the tests.
        return WebSearchResult(
            query=query,
            searched_at="2026-04-30T00:00:00+00:00",
            freshness=freshness,
            sources=tuple(
                WebSearchSource(
                    url=f"https://{hostname}/article",
                    title=f"{hostname} の記事",
                    hostname=hostname,
                    age="",
                    snippets=(),
                    page_text=page_text,
                )
                for hostname in hostnames
            ),
        )

    def _followed_result(self):
        # 日本語: 検索結果ページ1件と、そこからリンクをたどった2件を持つ結果を組み立てます。
        # English: Build a result with one search-result page and two pages reached by links.
        def source(hostname, *, depth=0, parent="", page_text=""):
            return WebSearchSource(
                url=f"https://{hostname}/article",
                title=f"{hostname} の記事",
                hostname=hostname,
                age="",
                snippets=(),
                page_text=page_text,
                link_depth=depth,
                linked_from_url=parent,
            )

        return WebSearchResult(
            query="Python news",
            searched_at="2026-04-30T00:00:00+00:00",
            sources=(
                source("root.example", page_text="root body"),
                source(
                    "child.example",
                    depth=1,
                    parent="https://www.root.example/article",
                    page_text="child body",
                ),
                source(
                    "grand.example",
                    depth=2,
                    parent="https://child.example/article",
                    page_text="grand body",
                ),
            ),
        )

    # 日本語: 実行記録が、要約と、ID・種類・状態を持つステップの並びを返すことを検証します。
    # English: Verify the record returns a summary and an ordered list of steps carrying id, kind and status.
    def test_build_answer_trace_returns_summary_and_steps(self):
        result = self._result("Python news", ["example.com"])

        record = trace.build_answer_trace(steps=[trace.search_step(result), trace.review_step(result)])

        self.assertEqual(record["version"], 1)
        self.assertEqual(record["summary"], "Web検索1回 · 参照サイト1件")
        self.assertEqual(
            [(step["id"], step["kind"], step["status"], step["title"]) for step in record["steps"]],
            [("s1", "search", "done", "Web検索"), ("s2", "review", "done", "検索結果を確認")],
        )

    # 日本語: 出典 1 件が、リンク・favicon・頭文字・たどった階層を描ける形で渡ることを検証します。
    # English: Verify one source is handed over with what the screen needs: link, favicon, initial and followed depth.
    def test_source_carries_link_favicon_and_depth(self):
        record = trace.build_answer_trace(steps=[trace.deep_read_step(self._followed_result())])

        self.assertEqual(
            record["steps"][0]["sources"],
            [
                {
                    "url": "https://child.example/article",
                    "title": "child.example の記事",
                    "hostname": "child.example",
                    # 出典が固有の favicon を持たないときは、サイト直下のものへ解決する。
                    # A source without a favicon of its own resolves to the one at the site root.
                    "favicon_url": "https://child.example/favicon.ico",
                    "fallback_label": "C",
                    "link_depth": 1,
                    "linked_from": "root.example",
                },
                {
                    "url": "https://grand.example/article",
                    "title": "grand.example の記事",
                    "hostname": "grand.example",
                    "favicon_url": "https://grand.example/favicon.ico",
                    "fallback_label": "G",
                    "link_depth": 2,
                    "linked_from": "child.example",
                },
            ],
        )

    # 日本語: 追加検索も1回目と同じように出典を展開できることを検証します。
    # English: Verify a follow-up search expands its own sources just like the first one.
    def test_every_search_step_carries_its_own_sources(self):
        first = self._result("Python news", ["first.example"])
        second = self._result("Python release", ["second.example", "third.example"])

        record = trace.build_answer_trace(
            steps=[
                trace.search_step(first),
                trace.search_step(second, additional=True),
            ]
        )

        self.assertEqual([step["title"] for step in record["steps"]], ["Web検索", "追加検索"])
        self.assertEqual(
            [[source["url"] for source in step["sources"]] for step in record["steps"]],
            [
                ["https://first.example/article"],
                ["https://second.example/article", "https://third.example/article"],
            ],
        )

    # 日本語: ステップに検索語・件数・ドメインチップが表示されることを検証します。
    # English: Verify a step surfaces its query, result count, and domain chips.
    def test_search_step_shows_query_count_and_domains(self):
        result = self._result(
            "Python 3.13",
            ["a.example", "b.example", "c.example", "d.example"],
            freshness="pw",
        )

        step = trace.build_answer_trace(steps=[trace.search_step(result)])["steps"][0]

        self.assertEqual(step["query"], "Python 3.13")
        self.assertEqual(step["badge"], "4件")
        # 上限を超えたドメインは「+N」に畳む
        # Domains beyond the display limit are collapsed into a "+N" chip.
        self.assertEqual(step["chips"], ["a.example", "b.example", "c.example", "+1"])
        self.assertIn("1週間以内の情報に絞り込んで", step["detail"])

    # 日本語: 本文まで読めたときだけ精読ステップを出すことを検証します。
    # English: Verify the page-read step appears only when page text was retrieved.
    def test_page_read_step_only_when_page_text_exists(self):
        self.assertIsNone(trace.page_read_step(self._result("q", ["example.com"])))

        step = trace.page_read_step(self._result("q", ["example.com"], page_text="body"))

        self.assertIsNotNone(step)
        self.assertEqual(step.kind, "read")
        self.assertIn("example.com", step.detail)

    # 日本語: リンクをたどって読んだページが、件数・最大深さ・起点付きの専用ステップになることを検証します。
    # English: Verify followed pages get their own step with count, max depth, and origin.
    def test_deep_read_step_reports_count_depth_and_origin(self):
        result = self._followed_result()

        step = trace.deep_read_step(result)

        self.assertIsNotNone(step)
        self.assertEqual(step.kind, "follow")
        self.assertEqual(step.title, "リンクをたどって深掘り")
        self.assertEqual(step.badge, "2件・最大2階層")
        self.assertIn("「root.example」など検索結果のページから", step.detail)
        self.assertIn("最大2階層先までの2件", step.detail)
        self.assertEqual(step.chips, ("child.example", "grand.example"))

    # 日本語: 深掘りステップの一覧には、たどって到達したページだけが並ぶことを検証します。
    # English: Verify the deep-read step lists only the pages reached by following links.
    def test_deep_read_step_lists_only_followed_pages(self):
        step = trace.deep_read_step(self._followed_result())

        urls = [source.url for source in step.sources.sources]

        self.assertEqual(
            urls,
            ["https://child.example/article", "https://grand.example/article"],
        )

    # 日本語: 精読ステップは検索結果ページだけを数え、深掘り分を含めないことを検証します。
    # English: Verify the page-read step counts only result pages, never followed ones.
    def test_page_read_step_excludes_followed_pages(self):
        result = self._followed_result()

        step = trace.page_read_step(result)

        self.assertEqual(step.badge, "1件")
        self.assertEqual([source.url for source in step.sources.sources], ["https://root.example/article"])

    # 日本語: リンクをたどっていなければ深掘りステップを出さないことを検証します。
    # English: Verify no deep-read step appears when no link was followed.
    def test_deep_read_step_absent_without_followed_pages(self):
        self.assertIsNone(trace.deep_read_step(None))
        self.assertIsNone(trace.deep_read_step(self._result("q", ["example.com"], page_text="body")))

    # 日本語: 本文取得のステップが「精読 → 深掘り」の順で並ぶことを検証します。
    # English: Verify the page-reading steps come back in read-then-follow order.
    def test_page_reading_steps_are_ordered_read_then_follow(self):
        steps = trace.page_reading_steps(self._followed_result())

        self.assertEqual([step.kind for step in steps], ["read", "follow"])

    # 日本語: たどり元が分からなくても階層は渡し、たどり元は空にすることを検証します。
    # English: Verify the depth is still handed over when the origin is unknown, with the origin left empty.
    def test_followed_source_without_a_known_origin_keeps_its_depth(self):
        result = WebSearchResult(
            query="x",
            searched_at="2026-04-30T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://child.example/b",
                    title="Child",
                    hostname="child.example",
                    age="",
                    snippets=(),
                    page_text="body",
                    link_depth=1,
                    linked_from_url="",
                ),
            ),
        )

        source = trace.build_answer_trace(steps=[trace.deep_read_step(result)])["steps"][0]["sources"][0]

        self.assertEqual((source["link_depth"], source["linked_from"]), (1, ""))

    # 日本語: 検索結果のページ自体には、たどり元と階層を付けないことを検証します。
    # English: Verify search-result pages themselves carry no origin and no depth.
    def test_result_pages_carry_no_followed_depth(self):
        record = trace.build_answer_trace(steps=[trace.page_read_step(self._followed_result())])

        self.assertEqual(
            [(source["link_depth"], source["linked_from"]) for source in record["steps"][0]["sources"]],
            [(0, "")],
        )

    # 日本語: 深掘りの有無が折りたたみ時のサマリにも出ること、
    #         同じソースを複数ステップで数え直さないことを検証します。
    # English: Verify the collapsed summary mentions deep exploration and counts each source once.
    def test_summary_mentions_deep_exploration_and_counts_sources_once(self):
        result = self._followed_result()

        record = trace.build_answer_trace(
            steps=[
                trace.search_step(result),
                *trace.page_reading_steps(result),
            ]
        )

        self.assertEqual(record["summary"], "Web検索1回 · 参照サイト3件 · 本文精読あり · リンク深掘りあり")

    # 日本語: 再利用ステップが専用の見出しとアイコン種別になることを検証します。
    # English: Verify a reused search renders with its own title and kind.
    def test_cached_search_step_is_marked_as_reuse(self):
        result = self._result("Python news", ["example.com"])

        step = trace.search_step(result, cached=True)

        self.assertEqual(step.kind, "reuse")
        self.assertEqual(step.title, "検索結果を再利用")
        self.assertIsNotNone(step.sources)

    # 日本語: 検索失敗のステップが、警告の種類かつ失敗の状態で渡ることを検証します。
    # English: Verify a failed search is handed over with the warning kind and the failed status.
    def test_failed_search_step_is_a_failed_warning(self):
        step = trace.build_answer_trace(
            steps=[trace.search_failed_step("Python news", reason="上限に達しました。")]
        )["steps"][0]

        self.assertEqual((step["kind"], step["status"]), ("warning", "failed"))
        self.assertEqual(step["detail"], "上限に達しました。")

    # 日本語: 選択した参照元 (メモ・共有プロンプト) の検索ステップが、件数と検索の種類を表示することを検証します。
    # English: Verify selected-reference lookup steps (memos, shared prompts) show counts and the type of search.
    def test_selected_reference_steps_show_counts_and_search_types(self):
        record = trace.build_answer_trace(
            steps=[
                trace.selected_reference_step(
                    PERSONAL_KNOWLEDGE_SOURCE,
                    {"status": "ok", "memo_count": 2},
                    query="好みのカフェ",
                ),
                trace.selected_reference_step(
                    SHARED_PROMPT_SOURCE,
                    {"status": "ok", "prompt_count": 3},
                    query="集中力 回復",
                ),
            ]
        )

        knowledge, prompt = record["steps"]
        self.assertEqual((knowledge["kind"], knowledge["title"]), ("knowledge", "メモを検索"))
        self.assertEqual(knowledge["chips"], ["メモ 2件"])
        # メモの検索のステップは、記憶に触れない。
        # The memo step never mentions memory.
        self.assertNotIn("記憶", json.dumps(knowledge, ensure_ascii=False))
        self.assertEqual((prompt["kind"], prompt["title"]), ("prompt", "共有プロンプトを検索"))
        self.assertEqual(record["summary"], "メモ検索あり · 共有プロンプト検索あり")

    # 日本語: 参照元の検索に失敗したときは警告ステップになることを検証します。
    # English: Verify a failed reference lookup becomes a warning step.
    def test_failed_selected_reference_lookup_uses_warning_kind(self):
        step = trace.selected_reference_step(
            PERSONAL_KNOWLEDGE_SOURCE,
            {"status": "failed"},
            query="旅行",
        )

        self.assertEqual(step.kind, "warning")
        self.assertIn("検索に失敗", step.detail)

    # 日本語: dict形式の旧ステップも受け付け、種別を推定することを検証します。
    # English: Verify legacy dict steps are accepted and their kind inferred.
    def test_legacy_dict_steps_are_supported(self):
        step = trace.build_answer_trace(steps=[{"title": "回答を作成", "detail": "まとめました。"}])["steps"][0]

        self.assertEqual((step["title"], step["kind"]), ("回答を作成", "answer"))

    # 日本語: 画面名を「記憶」に改める前に保存された題名（メモとマイコンテキスト）も、知識ステップとして読み取ることを検証します。
    # English: Verify titles saved before the screen name became "記憶" are still read as knowledge steps.
    def test_legacy_dict_step_with_old_memory_title_keeps_knowledge_kind(self):
        record = trace.build_answer_trace(
            steps=[
                {"title": "メモとマイコンテキストを検索", "detail": "保存済みの内容を読みました。"},
                {"title": "メモと記憶を検索", "detail": "保存済みの内容を読みました。"},
            ]
        )

        self.assertEqual([step["kind"] for step in record["steps"]], ["knowledge", "knowledge"])

    # 日本語: どのステップにも紐付かない検索結果は、出典を持つ独立したステップとして末尾に足すことを検証します。
    # English: Verify sources with no owning step are appended as a step of their own that carries them.
    def test_result_without_step_sources_falls_back_to_its_own_step(self):
        result = self._result("Python news", ["example.com"])

        record = trace.build_answer_trace(
            result,
            steps=[{"title": "回答を作成", "detail": "まとめました。"}],
        )

        fallback = record["steps"][-1]
        self.assertEqual(len(record["steps"]), 2)
        self.assertEqual((fallback["kind"], fallback["title"], fallback["badge"]), ("search", "参照したWebサイト", "1件"))
        self.assertEqual(fallback["detail"], "「Python news」の検索結果を回答の根拠に使いました。")
        self.assertEqual([source["url"] for source in fallback["sources"]], ["https://example.com/article"])
        self.assertEqual(record["summary"], "参照サイト1件")

    # 日本語: ステップに出典が付いている場合は、独立したステップを重ねて足さないことを検証します。
    # English: Verify no extra step is appended when a step already owns the sources.
    def test_fallback_step_is_skipped_when_a_step_owns_sources(self):
        result = self._result("Python news", ["example.com"])

        record = trace.build_answer_trace(result, steps=[trace.search_step(result)])

        self.assertEqual([step["title"] for step in record["steps"]], ["Web検索"])

    # 日本語: ステップの文字列はマークアップにせず、そのままの文字列で渡すことを検証します（エスケープは描画する側が行う）。
    # English: Verify step strings are handed over as plain text, never as markup (escaping belongs to the renderer).
    def test_step_content_stays_plain_text(self):
        step = trace.build_answer_trace(
            steps=[
                {
                    "title": "<b>Unsafe</b>",
                    "detail": "<script>alert(1)</script>",
                    "query": "<img src=x>",
                }
            ]
        )["steps"][0]

        self.assertEqual(
            (step["title"], step["detail"], step["query"]),
            ("<b>Unsafe</b>", "<script>alert(1)</script>", "<img src=x>"),
        )

    # 日本語: 未知の種別は既定のアイコン種別へ寄せることを検証します。
    # English: Verify unknown kinds fall back to the default kind.
    def test_unknown_kind_falls_back_to_default(self):
        step = trace.build_answer_trace(steps=[{"title": "何かの処理", "kind": "totally-unknown"}])["steps"][0]

        self.assertEqual(step["kind"], "info")

    # 日本語: 実行中のステップは、実行中の状態と検索語を持って渡ることを検証します。
    # English: Verify a running step is handed over with the running status and its query.
    def test_running_search_step_is_handed_over_as_running(self):
        step = trace.build_answer_trace(steps=[trace.running_search_step("Python news")])["steps"][0]

        self.assertEqual((step["kind"], step["status"], step["title"], step["query"]), ("search", "running", "Web検索", "Python news"))
        self.assertEqual(step["badge"], "実行中")
        self.assertEqual(step["sources"], [])

    # 日本語: 実行中のステップを結果のステップへ置き換えても、同じ位置のステップは同じ ID を保つことを検証します。
    # English: Verify the step keeps its id when a running step is replaced in place by its result.
    def test_step_id_survives_the_change_from_running_to_done(self):
        result = self._result("Python news", ["example.com"])
        before = [trace.review_step(None), trace.running_search_step("Python news", additional=True)]
        after = [trace.review_step(None), trace.search_step(result, additional=True), trace.review_step(result)]

        running = trace.build_answer_trace(steps=before)["steps"][1]
        done = trace.build_answer_trace(steps=after)["steps"][1]

        self.assertEqual((running["id"], running["status"], running["title"]), ("s2", "running", "追加検索"))
        self.assertEqual((done["id"], done["status"], done["title"]), ("s2", "done", "追加検索"))

    # 日本語: 回答を確定する時点で実行中のまま残ったステップは、完了ではなく失敗として確定することを検証します。
    # English: Verify a step still running when the answer is settled becomes failed, never done.
    def test_steps_left_running_are_settled_as_failed(self):
        result = self._result("Python news", ["example.com"])
        settled = trace.settle_running_steps(
            [trace.search_step(result), trace.running_search_step("Python release")]
        )

        record = trace.build_answer_trace(steps=settled)

        self.assertEqual([step["status"] for step in record["steps"]], ["done", "failed"])
        interrupted = record["steps"][1]
        self.assertEqual((interrupted["kind"], interrupted["title"], interrupted["query"]), ("warning", "Web検索", "Python release"))
        self.assertEqual(interrupted["badge"], "")
        self.assertNotIn("実行しています", interrupted["detail"])

    # 日本語: 要約には終わったステップだけを数え、実行中の検索を「検索 1 回」と見せないことを検証します。
    # English: Verify the summary counts finished steps only, so a search still running does not read as one search done.
    def test_summary_does_not_count_a_running_search(self):
        result = self._result("Python news", ["example.com"])

        running_only = trace.build_answer_trace(steps=[trace.running_search_step("Python news")])
        one_done = trace.build_answer_trace(
            steps=[trace.search_step(result), trace.running_search_step("Python release", additional=True)]
        )

        self.assertEqual(running_only["summary"], "")
        self.assertEqual(one_done["summary"], "Web検索1回 · 参照サイト1件")

    # 日本語: 配信済みの記録に実行中のまま残ったステップは、同じ ID のまま失敗として確定することを検証します。
    # English: Verify a step left running in a published record is settled as failed under the same id.
    def test_published_record_with_a_running_step_is_settled_as_failed(self):
        result = self._result("Python news", ["example.com"])
        published = trace.build_answer_trace(
            steps=[trace.search_step(result), trace.running_search_step("Python release", additional=True)]
        )

        settled = trace.settle_running_answer_trace(published)

        self.assertEqual(settled["steps"][0], published["steps"][0])
        interrupted = settled["steps"][1]
        self.assertEqual(
            (interrupted["id"], interrupted["kind"], interrupted["status"], interrupted["title"], interrupted["query"]),
            ("s2", "warning", "failed", "追加検索", "Python release"),
        )
        self.assertEqual((interrupted["badge"], interrupted["sources"]), ("", []))
        # 実行中のステップが無い記録と、記録が無い場合は、そのまま返す。
        # A record with no running step, and no record at all, are returned as they are.
        self.assertIs(trace.settle_running_answer_trace(settled), settled)
        self.assertIsNone(trace.settle_running_answer_trace(None))

    # 日本語: 実行中のステップと結果のステップが同じ題名を使うことを検証します（同じ ID のまま状態だけが変わって見えるように）。
    # English: Verify a running step and its result share one title, so only the status appears to change under the same id.
    def test_running_steps_share_their_title_with_the_result_step(self):
        self.assertEqual(
            trace.running_reference_step(PERSONAL_KNOWLEDGE_SOURCE, "q").title,
            trace.selected_reference_step(PERSONAL_KNOWLEDGE_SOURCE, {"status": "ok", "memo_count": 1}, query="q").title,
        )
        self.assertEqual(
            trace.running_reference_step(SHARED_PROMPT_SOURCE, "q").title,
            trace.selected_reference_step(SHARED_PROMPT_SOURCE, {"status": "ok", "prompt_count": 1}, query="q").title,
        )
        self.assertEqual(trace.running_known_page_read_step().title, trace.known_page_read_step().title)

    # 日本語: ステップも出典も無い場合は実行記録を作らないことを検証します。
    # English: Verify no record is built when there is nothing to show.
    def test_returns_none_without_steps_or_sources(self):
        self.assertIsNone(trace.build_answer_trace(None, steps=[]))
        self.assertIsNone(trace.build_answer_trace(None, steps=[{"title": "  "}]))
