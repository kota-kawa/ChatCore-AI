"""Regression tests for the commit_email_change duplicate-email race.

``SELECT ... FOR UPDATE`` only locks rows it finds.  When no row matches the
target email (the common case), it locks nothing, so two concurrent requests
changing different users' emails to addresses that only differ by case
(``Foo@x.com`` / ``foo@x.com``) can both see zero matching rows and both
commit, producing a duplicate the ``lower(email)`` comparison was meant to
prevent.  commit_email_change now takes a ``pg_advisory_xact_lock`` keyed on
the normalized target email first, so concurrent attempts to claim the same
address serialize instead of racing.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects.postgresql import dialect

from services.repositories.user_repository import UserRepository


def _make_session(*, current_user=None, rowcount=1):
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=current_user)

    async def _execute(*args, **kwargs):
        result = MagicMock()
        result.rowcount = rowcount
        return result

    session.execute.side_effect = _execute
    return session


class _User:
    def __init__(self, id_):
        self.id = id_


class CommitEmailChangeTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_acquires_an_advisory_lock_keyed_on_the_normalized_target_email(self):
        session = _make_session(current_user=None)
        repository = UserRepository(session)

        await repository.commit_email_change(1, "New@Example.com")

        self.assertGreaterEqual(session.execute.await_count, 1)
        lock_call = session.execute.await_args_list[0]
        statement, params = lock_call.args
        compiled = str(statement.compile(dialect=dialect()))
        self.assertIn("pg_advisory_xact_lock", compiled)
        self.assertIn("hashtext", compiled)
        self.assertEqual(params["lock_key"], "user-email-change:new@example.com")

    async def test_lock_is_acquired_before_the_duplicate_check(self):
        call_order = []
        session = MagicMock()

        async def _execute(*args, **kwargs):
            call_order.append("execute")
            result = MagicMock()
            result.rowcount = 1
            return result

        async def _scalar(*args, **kwargs):
            call_order.append("scalar")

        session.execute = AsyncMock(side_effect=_execute)
        session.scalar = AsyncMock(side_effect=_scalar)
        repository = UserRepository(session)

        await repository.commit_email_change(1, "new@example.com")

        self.assertEqual(call_order[0], "execute")  # the advisory lock
        self.assertIn("scalar", call_order)
        self.assertLess(call_order.index("execute"), call_order.index("scalar"))

    async def test_same_email_owned_by_another_user_is_still_rejected(self):
        session = _make_session(current_user=_User(id_=2))
        repository = UserRepository(session)

        committed = await repository.commit_email_change(1, "taken@example.com")

        self.assertFalse(committed)

    async def test_owning_user_re_saving_their_own_email_is_accepted(self):
        session = _make_session(current_user=_User(id_=1), rowcount=1)
        repository = UserRepository(session)

        committed = await repository.commit_email_change(1, "mine@example.com")

        self.assertTrue(committed)

    async def test_no_conflict_commits_the_update(self):
        session = _make_session(current_user=None, rowcount=1)
        repository = UserRepository(session)

        committed = await repository.commit_email_change(1, "fresh@example.com")

        self.assertTrue(committed)


if __name__ == "__main__":
    unittest.main()
