"""プロンプトの表示回数（インプレッション）の記録を検証するテスト。
リポジトリの upsert SQL、記録エンドポイントの入力検証、カウンタ表と注目列を追加するマイグレーションを確かめる。

Tests for recording prompt impressions: the repository's upsert SQL, the endpoint's input validation,
and the migration that adds the counter table and the featured column.
"""

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect

from blueprints.prompt_share.prompt_share_api import record_prompt_impressions
from services.repositories.prompt_impression_repository import PromptImpressionRepository
from tests.helpers.request_helpers import build_request

MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260924_02_add_prompt_impressions_and_featured.py"
)


# 公開中のプロンプトだけを対象にした表示回数の upsert が、期待する SQL になることを検証するテストクラス。
# Test class verifying that the impression upsert targets only live public prompts and compiles to the expected SQL.
class PromptImpressionRepositoryTestCase(unittest.TestCase):
    def _run(self, prompt_ids, returned_ids):
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = returned_ids
        session.execute = AsyncMock(return_value=result)
        counted = asyncio.run(PromptImpressionRepository().increment_public_impressions(session, prompt_ids))
        return session, counted

    def test_upserts_one_impression_per_active_public_prompt(self):
        session, counted = self._run([3, 7, 3], [3, 7])

        self.assertEqual(counted, 2)
        statement = session.execute.await_args.args[0]
        compiled = str(statement.compile(dialect=dialect()))
        self.assertIn("INSERT INTO prompt_impression_counts", compiled)
        self.assertIn("prompts.is_public IS true", compiled)
        self.assertIn("prompts.deleted_at IS NULL", compiled)
        self.assertIn("ON CONFLICT (prompt_id) DO UPDATE", compiled)
        self.assertIn("impression_count + ", compiled)
        # 同じリクエスト内で ID が重複していても 1 回として数える。
        # Duplicate IDs in one request still count once.
        self.assertIn([3, 7], [list(value) for value in statement.compile().params.values() if isinstance(value, list)])

    def test_empty_batch_skips_the_database(self):
        session = MagicMock()
        session.execute = AsyncMock()

        counted = asyncio.run(PromptImpressionRepository().increment_public_impressions(session, []))

        self.assertEqual(counted, 0)
        session.execute.assert_not_awaited()


# 表示回数の記録エンドポイントが件数を返し、空または過大なバッチを 400 で拒否することを検証するテストクラス。
# Test class verifying that the impression endpoint reports the counted number and rejects empty or oversized batches with 400.
class PromptImpressionEndpointTestCase(unittest.TestCase):
    def _post(self, body):
        request = build_request(
            method="POST",
            path="/prompt_share/api/prompts/impressions",
            json_body=body,
            headers=[(b"content-type", b"application/json")],
        )
        return asyncio.run(record_prompt_impressions(request))

    def test_counts_the_batch_and_reports_how_many_were_counted(self):
        with patch("blueprints.prompt_share.prompt_share_api._service") as service_factory:
            service_factory.return_value.record_public_impressions = AsyncMock(return_value=2)
            response = self._post({"prompt_ids": [3, 7]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode()), {"status": "success", "counted": 2})
        service_factory.return_value.record_public_impressions.assert_awaited_once_with([3, 7])

    def test_rejects_an_empty_or_oversized_batch(self):
        with patch("blueprints.prompt_share.prompt_share_api._service") as service_factory:
            for body in ({"prompt_ids": []}, {"prompt_ids": list(range(101))}, {"prompt_ids": ["x"]}):
                with self.subTest(body=body):
                    response = self._post(body)
                    self.assertEqual(response.status_code, 400)
        service_factory.assert_not_called()


# 表示回数カウンタ表と featured_at 列を追加するマイグレーションの内容を検証するテストクラス。
# Test class for the migration that adds the impression counter table and the featured_at column.
class PromptImpressionMigrationTestCase(unittest.TestCase):
    def test_migration_adds_counter_table_and_featured_column(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

        self.assertIn('revision: str = "20260924_02"', source)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "20260924_01"', source)
        self.assertIn("CREATE TABLE IF NOT EXISTS prompt_impression_counts", upgrade)
        self.assertIn("ADD COLUMN IF NOT EXISTS featured_at TIMESTAMP", upgrade)
        self.assertIn("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_prompts_featured", upgrade)


if __name__ == "__main__":
    unittest.main()
