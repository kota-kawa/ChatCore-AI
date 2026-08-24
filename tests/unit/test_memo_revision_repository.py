import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect

from services.repositories.memo_repository import update_memo
from services.api_errors import ApiServiceError


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


def _result(*, mapping=None, revision=None):
    result = MagicMock()
    result.mappings.return_value.first.return_value = mapping
    result.scalar_one_or_none.return_value = revision
    return result


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
