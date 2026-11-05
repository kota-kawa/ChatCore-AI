"""メモの共有トークン作成（create_or_get_shared_memo_token）が、upsert、メモ未所有時の NotFound、トークン衝突
時の再試行を行うことを検証するテスト。

Tests create_or_get_shared_memo_token: the upsert, NotFound for a memo the user does not own, and retry on a token collision.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import IntegrityError

from services.api_errors import ResourceNotFoundError
from services.memo_share import create_or_get_shared_memo_token


# mappings().first() が row を返す DB 実行結果の代役を作る。
# Builds a database result stand-in whose mappings().first() returns row.
def _mapping_result(row):
    result = MagicMock()
    result.mappings.return_value.first.return_value = row
    return result


# session_scope の代役。begin() も同じオブジェクトを返す。
# Stand-in for session_scope; begin() returns the same object.
class _Scope:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def begin(self):
        return self


# PostgreSQL の一意制約違反（SQLSTATE 23505）を表す例外の代役。
# Exception stand-in for a PostgreSQL unique violation (SQLSTATE 23505).
class _PostgresUniqueViolationError(Exception):
    sqlstate = "23505"


# セッションと upsert をモックし、トークン衝突時は新しい非同期セッションで再試行されることを確かめる。
# Mocks the session and upsert and checks a token collision is retried in a new async session.
class MemoShareTokenTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_create_uses_async_upsert_and_returns_share_state(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=10)
        session.execute = AsyncMock(
            side_effect=[
                _mapping_result(None),
                _mapping_result(
                    {
                        "share_token": "fresh-token",
                        "expires_at": None,
                        "revoked_at": None,
                    }
                ),
            ]
        )
        state = await create_or_get_shared_memo_token(10, 20, session=session)

        self.assertEqual(state["share_token"], "fresh-token")
        self.assertTrue(state["is_active"])
        statement = session.execute.await_args_list[-1].args[0]
        self.assertIn("ON CONFLICT", str(statement))

    async def test_missing_owned_memo_raises_not_found_without_write(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=None)
        session.execute = AsyncMock()

        with self.assertRaises(ResourceNotFoundError):
            await create_or_get_shared_memo_token(99, 20, session=session)
        session.execute.assert_not_awaited()

    async def test_unique_token_collision_retries_with_a_new_async_session(self):
        duplicate = IntegrityError("insert", {}, _PostgresUniqueViolationError())
        with patch(
            "services.memo_share._create_once",
            new=AsyncMock(
                side_effect=[
                    duplicate,
                    {
                        "share_token": "fresh-token",
                        "is_active": True,
                        "is_reused": False,
                    },
                ]
            ),
        ) as create_once, patch(
            "services.memo_share.session_scope",
            side_effect=[_Scope(), _Scope()],
        ), patch(
            "services.memo_share.secrets.token_urlsafe",
            side_effect=["collision-token", "fresh-token"],
        ):
            state = await create_or_get_shared_memo_token(10, 20)

        self.assertEqual(state["share_token"], "fresh-token")
        self.assertEqual(create_once.await_count, 2)


if __name__ == "__main__":
    unittest.main()
