import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import IntegrityError

from services.api_errors import ResourceNotFoundError
from services.memo_share import create_or_get_shared_memo_token


def _mapping_result(row):
    result = MagicMock()
    result.mappings.return_value.first.return_value = row
    return result


class _Scope:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def begin(self):
        return self


class _PostgresUniqueViolation(Exception):
    sqlstate = "23505"


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
        duplicate = IntegrityError("insert", {}, _PostgresUniqueViolation())
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
