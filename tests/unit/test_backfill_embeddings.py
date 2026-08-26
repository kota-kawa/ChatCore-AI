import unittest
from unittest.mock import AsyncMock, patch

from scripts import backfill_embeddings


class BackfillTableTestCase(unittest.IsolatedAsyncioTestCase):
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
