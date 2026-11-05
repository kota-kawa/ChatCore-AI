"""メモ更新（memo_repository.update_memo）の楽観的ロックを検証するテスト。古いリビジョンの拒否、共有中メモの確認、読み取りと書き込みの間の競合検出を見る。

Tests the optimistic locking of memo_repository.update_memo: stale revisions, active shares needing acknowledgement,
and conflicts between read and write.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect

from services.api_errors import ApiServiceError
from services.repositories.memo_repository import update_memo


# 更新前のメモ行の辞書を作る。overrides で項目を上書きする。
# Builds the pre-update memo row as a dict; overrides replace fields.
def existing_memo(**overrides):
    memo = {
        "title": "Before",
        "ai_response": "body",
        "collection_id": None,
        "background_color": None,
        "revision": 4,
        "is_shared": False,
    }
    memo.update(overrides)
    return memo


# DB 実行結果の代役。mappings().first() と scalar_one_or_none() の値を指定できる。
# Stand-in for a database result with configurable mappings().first() and scalar_one_or_none() values.
def _result(*, mapping=None, revision=None):
    result = MagicMock()
    result.mappings.return_value.first.return_value = mapping
    result.scalar_one_or_none.return_value = revision
    return result


# セッションの execute を順番に差し替え、書き込み前に弾く場合と書き込み後に競合を検出する場合を確かめる。
# Replaces session.execute with ordered results and checks conflicts are rejected before the write or detected after it.
class MemoRevisionRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_update_uses_revision_and_active_share_guards(self):
        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=[
                _result(mapping=existing_memo()),
                _result(revision=5),
            ]
        )
        returned = {"id": 10, "title": "After", "ai_response": "body", "revision": 5}
        with patch(
            "services.repositories.memo_repository.fetch_memo_detail",
            new=AsyncMock(return_value=returned),
        ):
            result = await update_memo(
                7,
                10,
                title="After",
                ai_response=None,
                collection_id=None,
                clear_collection=False,
                expected_revision=4,
                allow_shared_content_change=False,
                session=session,
            )

        self.assertEqual(result["revision"], 5)
        statement = session.execute.await_args_list[1].args[0]
        compiled = statement.compile(dialect=dialect())
        self.assertIn("revision", str(compiled))
        self.assertIn("NOT (EXISTS", str(compiled))
        self.assertIn(4, compiled.params.values())

    async def test_update_rejects_stale_revision_before_write(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result(mapping=existing_memo(revision=5)))
        with self.assertRaises(ApiServiceError) as error:
            await update_memo(
                7,
                10,
                title="After",
                ai_response=None,
                collection_id=None,
                clear_collection=False,
                expected_revision=4,
                session=session,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(session.execute.await_count, 1)

    async def test_update_rejects_active_shared_memo_without_acknowledgement(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result(mapping=existing_memo(is_shared=True)))
        with self.assertRaises(ApiServiceError) as error:
            await update_memo(
                7,
                10,
                title="After",
                ai_response=None,
                collection_id=None,
                clear_collection=False,
                expected_revision=4,
                allow_shared_content_change=False,
                session=session,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("共有中", error.exception.message)

    async def test_update_detects_revision_change_between_read_and_write(self):
        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=[_result(mapping=existing_memo()), _result(revision=None)]
        )
        session.scalar = AsyncMock(return_value=True)
        with self.assertRaises(ApiServiceError) as error:
            await update_memo(
                7,
                10,
                title="After",
                ai_response=None,
                collection_id=None,
                clear_collection=False,
                expected_revision=4,
                session=session,
            )
        self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
