"""埋め込みベクトルの補完スクリプト(scripts/backfill_embeddings)を検証する単体テスト。
行ごとの生成と保存、空テキストのスキップ、プロバイダー停止時の中断、dry-run、各テーブルの本文組み立て、終了コードを確かめる。

Unit tests for the embedding backfill script (scripts/backfill_embeddings).
Covers per-row generation and storage, skipping empty text, aborting when the provider stops responding, dry-run,
per-table text building, and exit codes.
"""

import unittest
from unittest.mock import AsyncMock, patch

from scripts import backfill_embeddings


class BackfillTableTestCase(unittest.IsolatedAsyncioTestCase):
    # 日本語: DB 取得・保存・埋め込み生成を差し替えて _backfill_table を 1 回実行し、集計(stats)と保存された (id, ベクトル) を返す。
    #         取得は「rows を返した後は空」の 2 バッチで再現する。
    # English: Run _backfill_table once with DB fetch/store and embedding generation replaced, returning
    # the stats and the stored (id, vector) pairs.
    #          Fetching is simulated as two batches: the rows, then an empty one.
    async def _run(self, *, rows, generate, available=True):
        stored: list[tuple[int, list[float]]] = []
        batches = [list(rows), []]

        async def fake_fetch(_table, _columns, *, after_id, include_existing, batch_size):
            del after_id, include_existing, batch_size
            return batches.pop(0) if batches else []

        async def fake_store(row_id, embedding):
            stored.append((row_id, embedding))

        with (
            patch.object(
                backfill_embeddings,
                "_count_pending",
                new=AsyncMock(return_value=len(rows)),
            ),
            patch.object(backfill_embeddings, "_fetch_batch", side_effect=fake_fetch),
            patch.object(backfill_embeddings, "_store_embedding", new=fake_store),
            patch.object(backfill_embeddings, "generate_embedding", side_effect=generate),
            patch.object(backfill_embeddings, "embeddings_available", return_value=available),
        ):
            stats = await backfill_embeddings._backfill_table(
                label="memo_entries",
                table="memo_entries",
                columns="title, ai_response",
                build_text=backfill_embeddings._memo_text,
                store=fake_store,
                include_existing=False,
                limit=None,
                sleep_seconds=0.0,
                dry_run=False,
            )
        return stats, stored

    async def test_embeds_and_stores_each_row(self):
        rows = [(1, "タイトル", "本文"), (2, "title", "body")]

        stats, stored = await self._run(rows=rows, generate=lambda _text: [0.1, 0.2])

        self.assertEqual(stats.embedded, 2)
        self.assertEqual(stats.failed, 0)
        self.assertEqual([row_id for row_id, _ in stored], [1, 2])

    async def test_rows_without_text_are_skipped_rather_than_embedded(self):
        rows = [(1, "", ""), (2, "title", "body")]

        stats, stored = await self._run(rows=rows, generate=lambda _text: [0.1, 0.2])

        self.assertEqual(stats.skipped_empty, 1)
        self.assertEqual(stats.embedded, 1)
        self.assertEqual([row_id for row_id, _ in stored], [2])

    async def test_aborts_once_the_provider_stops_responding(self):
        rows = [(index, "title", "body") for index in range(1, 6)]

        stats, stored = await self._run(
            rows=rows,
            generate=lambda _text: None,
            available=False,
        )

        self.assertEqual(stats.embedded, 0)
        self.assertEqual(stats.failed, 1)
        self.assertEqual(stored, [])

    async def test_dry_run_reports_without_calling_the_provider(self):
        generate = AsyncMock(return_value=[0.1])
        with patch.object(
            backfill_embeddings, "_count_pending", new=AsyncMock(return_value=3)
        ):
            stats = await backfill_embeddings._backfill_table(
                label="memo_entries",
                table="memo_entries",
                columns="title, ai_response",
                build_text=backfill_embeddings._memo_text,
                store=AsyncMock(),
                include_existing=False,
                limit=None,
                sleep_seconds=0.0,
                dry_run=True,
            )

        self.assertEqual(stats.embedded, 0)
        generate.assert_not_awaited()


# 日本語: 埋め込み対象のテキスト(タイトル・本文・種別など)を行から組み立てる関数を確かめる。
# English: Checks the functions that build the text to embed (title, body, type, ...) from a row.
class BackfillTextBuildersTestCase(unittest.TestCase):
    def test_memo_text_combines_title_and_body(self):
        text = backfill_embeddings._memo_text((1, "設計メモ", "本文です"))

        self.assertIn("設計メモ", text)
        self.assertIn("本文です", text)

    def test_fact_text_includes_the_fact_type(self):
        text = backfill_embeddings._fact_text((1, "preference", "エディタ", "vim を使う"))

        self.assertIn("preference", text)
        self.assertIn("エディタ", text)
        self.assertIn("vim を使う", text)

    def test_prompt_text_falls_back_to_skill_markdown(self):
        text = backfill_embeddings._prompt_text((1, "Skill", "説明", "", {"skill_markdown": "# 手順"}))

        self.assertIn("Skill", text)
        self.assertIn("説明", text)
        self.assertIn("# 手順", text)


# 日本語: コマンドのエントリーポイント main の終了コード(埋め込み不可なら 1、--fail-on-pending で未処理があれば 1)を確かめる。
# English: Checks the exit codes of the main entry point: 1 when embeddings are unavailable, and 1 with --fail-on-pending
# when work is pending.
class BackfillMainTestCase(unittest.TestCase):
    def test_exits_non_zero_when_embeddings_are_unavailable(self):
        with patch.object(backfill_embeddings, "configure_logging"), patch.object(
            backfill_embeddings, "embeddings_available", return_value=False
        ):
            self.assertEqual(backfill_embeddings.main([]), 1)

    def test_fail_on_pending_reports_work_without_provider_access(self):
        with (
            patch.object(backfill_embeddings, "configure_logging"),
            patch.object(
                backfill_embeddings,
                "_count_pending",
                new=AsyncMock(return_value=1),
            ),
        ):
            self.assertEqual(backfill_embeddings.main(["--fail-on-pending"]), 1)


if __name__ == "__main__":
    unittest.main()
