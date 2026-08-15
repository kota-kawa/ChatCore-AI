import unittest

from services import web_search_trace as trace
from services.web_search import WebSearchResult, WebSearchSource


# 日本語: 「回答までのステップ」トレースUIのHTML生成を検証するテストクラスです。
# English: Test case class covering HTML generation for the answer-trace ("steps") UI.
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

    # 日本語: トレースブロックが見出しとステップのタイムラインを返すことを検証します。
    # English: Verify the trace block returns a summary and a step timeline.
    def test_build_trace_markdown_returns_summary_and_steps(self):
        result = self._result("Python news", ["example.com"])

        block = trace.build_web_search_trace_markdown(
            steps=[trace.decision_step(result), trace.search_step(result)]
        )

        self.assertIn('<details class="web-search-sources web-search-sources--trace">', block)
        self.assertIn('<span class="web-search-sources__label">回答までのステップ</span>', block)
        self.assertIn('<span class="web-search-sources__count">2ステップ</span>', block)
        self.assertIn(
            '<span class="web-search-sources__summary-detail">Web検索1回 · 参照サイト1件</span>',
            block,
        )
        self.assertIn('<ol class="web-search-sources__steps">', block)
        self.assertIn('<span class="web-search-sources__step-title">検索が必要か判断</span>', block)
        self.assertIn('<i class="bi bi-search"></i>', block)
        self.assertNotIn('<details class="web-search-sources__step-details" open', block)

    # 日本語: 空行を挟まないことで、Markdown内のHTMLブロックが途切れないことを検証します。
    # English: Verify no blank line is emitted so the HTML block survives Markdown rendering.
    def test_build_trace_markdown_never_emits_blank_lines(self):
        block = trace.build_web_search_trace_markdown(
            steps=[trace.answer_step([])],
        )

        self.assertTrue(block)
        self.assertNotIn("\n\n", block)

    # 日本語: 追加検索も1回目と同じように出典を展開できることを検証します。
    # English: Verify a follow-up search expands its own sources just like the first one.
    def test_every_search_step_carries_its_own_sources(self):
        first = self._result("Python news", ["first.example"])
        second = self._result("Python release", ["second.example", "third.example"])

        block = trace.build_web_search_trace_markdown(
            steps=[
                trace.search_step(first),
                trace.search_step(second, additional=True),
            ]
        )

        self.assertEqual(block.count('<details class="web-search-sources__step-details">'), 2)
        self.assertEqual(block.count('<div class="web-search-sources__step-body">'), 2)
        self.assertEqual(
            block.count('<span class="web-search-sources__step-toggle-label">参照したWebサイト</span>'),
            2,
        )
        self.assertIn('<span class="web-search-sources__step-title">Web検索</span>', block)
        self.assertIn('<span class="web-search-sources__step-title">追加検索</span>', block)
        self.assertIn("https://first.example/article", block)
        self.assertIn("https://second.example/article", block)
        self.assertIn('<span class="web-search-sources__step-toggle-count">2件</span>', block)

    # 日本語: ステップに検索語・件数・ドメインチップが表示されることを検証します。
    # English: Verify a step surfaces its query, result count, and domain chips.
    def test_search_step_shows_query_count_and_domains(self):
        result = self._result(
            "Python 3.13",
            ["a.example", "b.example", "c.example", "d.example"],
            freshness="pw",
        )

        block = trace.build_web_search_trace_markdown(steps=[trace.search_step(result)])

        self.assertIn('<span class="web-search-sources__step-query">Python 3.13</span>', block)
        self.assertIn('<span class="web-search-sources__step-badge">4件</span>', block)
        self.assertIn('<span class="web-search-sources__step-chip">a.example</span>', block)
        # 上限を超えたドメインは「+N」に畳む
        self.assertIn('<span class="web-search-sources__step-chip">+1</span>', block)
        self.assertIn("1週間以内の情報に絞り込んで", block)

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

    # 日本語: 深掘りしたページに、辿り元と深さの表示が付くことを検証します。
    # English: Verify followed pages render their origin and depth in the source list.
    def test_followed_sources_render_depth_marker(self):
        block = trace.build_web_search_trace_markdown(
            steps=[trace.deep_read_step(self._followed_result())]
        )

        self.assertIn(
            '<span class="web-search-sources__depth">root.example から1階層先</span>',
            block,
        )
        self.assertIn(
            '<span class="web-search-sources__depth">child.example から2階層先</span>',
            block,
        )
        self.assertEqual(block.count('<li class="web-search-sources__item--followed"'), 0)
        self.assertEqual(
            block.count('<li class="web-search-sources__item web-search-sources__item--followed">'),
            2,
        )

    # 日本語: 深掘りの有無が折りたたみ時のサマリにも出ること、
    #         同じソースを複数ステップで数え直さないことを検証します。
    # English: Verify the collapsed summary mentions deep exploration and counts each source once.
    def test_summary_mentions_deep_exploration_and_counts_sources_once(self):
        result = self._followed_result()

        block = trace.build_web_search_trace_markdown(
            steps=[
                trace.search_step(result),
                *trace.page_reading_steps(result),
            ]
        )

        self.assertIn(
            '<span class="web-search-sources__summary-detail">'
            "Web検索1回 · 参照サイト3件 · 本文精読あり · リンク深掘りあり</span>",
            block,
        )

    # 日本語: 再利用ステップが専用の見出しとアイコン種別になることを検証します。
    # English: Verify a reused search renders with its own title and kind.
    def test_cached_search_step_is_marked_as_reuse(self):
        result = self._result("Python news", ["example.com"])

        step = trace.search_step(result, cached=True)

        self.assertEqual(step.kind, "reuse")
        self.assertEqual(step.title, "検索結果を再利用")
        self.assertIsNotNone(step.sources)

    # 日本語: 検索失敗のステップが警告表示になることを検証します。
    # English: Verify a failed search renders as a warning step.
    def test_failed_search_step_uses_warning_kind(self):
        block = trace.build_web_search_trace_markdown(
            steps=[trace.search_failed_step("Python news", reason="上限に達しました。")]
        )

        self.assertIn("web-search-sources__step-marker--warning", block)
        self.assertIn("上限に達しました。", block)

    # 日本語: dict形式の旧ステップも受け付け、種別を推定することを検証します。
    # English: Verify legacy dict steps are accepted and their kind inferred.
    def test_legacy_dict_steps_are_supported(self):
        block = trace.build_web_search_trace_markdown(
            steps=[{"title": "回答を作成", "detail": "まとめました。"}]
        )

        self.assertIn('<span class="web-search-sources__step-title">回答を作成</span>', block)
        self.assertIn("web-search-sources__step--answer", block)

    # 日本語: ステップに紐付かない検索結果も展開ブロックとして描画することを検証します。
    # English: Verify sources with no owning step still render as an expandable block.
    def test_result_without_step_sources_falls_back_to_its_own_block(self):
        result = self._result("Python news", ["example.com"])

        block = trace.build_web_search_trace_markdown(
            result,
            steps=[{"title": "回答を作成", "detail": "まとめました。"}],
        )

        self.assertIn('<details class="web-search-sources__step-details">', block)
        self.assertIn("https://example.com/article", block)
        self.assertIn('<span class="web-search-sources__count">2ステップ</span>', block)

    # 日本語: ステップに出典が付いている場合はフォールバックを重複させないことを検証します。
    # English: Verify the fallback block is skipped when a step already owns the sources.
    def test_fallback_block_is_skipped_when_a_step_owns_sources(self):
        result = self._result("Python news", ["example.com"])

        block = trace.build_web_search_trace_markdown(result, steps=[trace.search_step(result)])

        self.assertEqual(block.count('<details class="web-search-sources__step-details">'), 1)

    # 日本語: ステップのタイトル・説明・検索語をエスケープすることを検証します。
    # English: Verify step titles, details, and queries are escaped.
    def test_step_content_is_escaped(self):
        block = trace.build_web_search_trace_markdown(
            steps=[
                {
                    "title": "<b>Unsafe</b>",
                    "detail": "<script>alert(1)</script>",
                    "query": "<img src=x>",
                }
            ]
        )

        self.assertIn("&lt;b&gt;Unsafe&lt;/b&gt;", block)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", block)
        self.assertIn("&lt;img src=x&gt;", block)
        self.assertNotIn("<b>Unsafe</b>", block)

    # 日本語: 未知の種別は既定のアイコン種別へ寄せることを検証します。
    # English: Verify unknown kinds fall back to the default kind.
    def test_unknown_kind_falls_back_to_default(self):
        block = trace.build_web_search_trace_markdown(
            steps=[{"title": "何かの処理", "kind": "totally-unknown"}]
        )

        self.assertIn("web-search-sources__step--info", block)
        self.assertNotIn("totally-unknown", block)

    # 日本語: ステップも出典も無い場合は空文字を返すことを検証します。
    # English: Verify an empty string is returned when there is nothing to show.
    def test_returns_empty_without_steps_or_sources(self):
        self.assertEqual(trace.build_web_search_trace_markdown(None, steps=[]), "")
        self.assertEqual(trace.build_web_search_trace_markdown(None, steps=[{"title": "  "}]), "")


if __name__ == "__main__":
    unittest.main()
