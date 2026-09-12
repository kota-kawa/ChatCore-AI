"""Repository-level rules for revoked and expired chat share links."""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.error_messages import ERROR_CHAT_ROOM_SHARE_FORBIDDEN, ERROR_SHARED_LINK_NOT_FOUND
from services.models import ChatRoom
from services.repositories.chat_repository import ChatRepository


def _compile(statement) -> str:
    return str(statement.compile(dialect=postgresql_dialect()))


class _NestedTransaction:
    """Stand-in for ``AsyncSession.begin_nested()`` used by the token upsert."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def _owner_result(user_id: int = 7):
    result = Mock()
    result.scalar_one_or_none.return_value = ChatRoom(id="room-1", user_id=user_id)
    return result


def _mapping_result(row):
    result = Mock()
    result.mappings.return_value.first.return_value = row
    return result


def _session(*results):
    session = Mock()
    session.execute = AsyncMock(side_effect=list(results))
    session.begin_nested = Mock(return_value=_NestedTransaction())
    return session


class SharedChatRoomLookupTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_public_lookup_filters_revoked_and_expired_links(self):
        result = Mock()
        result.one_or_none.return_value = None
        session = Mock()
        session.execute = AsyncMock(return_value=result)

        with self.assertRaises(ResourceNotFoundError) as raised:
            await ChatRepository(session).get_shared_chat_room_payload("dead-token")

        self.assertEqual(str(raised.exception), ERROR_SHARED_LINK_NOT_FOUND)
        sql = _compile(session.execute.await_args.args[0])
        self.assertIn("shared_chat_rooms.revoked_at IS NULL", sql)
        self.assertIn("shared_chat_rooms.expires_at IS NULL", sql)
        self.assertIn("shared_chat_rooms.expires_at > CURRENT_TIMESTAMP", sql)


class CreateOrGetSharedChatTokenTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_active_link_is_reused_without_writing(self):
        active = {"share_token": "live-token", "expires_at": None, "revoked_at": None}
        session = _session(_owner_result(), _mapping_result(active))

        state = await ChatRepository(session).create_or_get_shared_chat_token("room-1", 7)

        self.assertEqual(state["share_token"], "live-token")
        self.assertTrue(state["is_reused"])
        self.assertEqual(session.execute.await_count, 2)

    async def test_revoked_link_is_replaced_by_a_new_token(self):
        revoked = {
            "share_token": "dead-token",
            "expires_at": None,
            "revoked_at": datetime(2026, 9, 1, tzinfo=UTC),
        }
        fresh = {"share_token": "fresh-token", "expires_at": None, "revoked_at": None}
        session = _session(_owner_result(), _mapping_result(revoked), _mapping_result(fresh))

        state = await ChatRepository(session).create_or_get_shared_chat_token("room-1", 7)

        self.assertEqual(state["share_token"], "fresh-token")
        self.assertFalse(state["is_reused"])
        sql = _compile(session.execute.await_args.args[0])
        self.assertIn("ON CONFLICT", sql)
        self.assertIn("revoked_at", sql)

    async def test_expired_link_is_replaced_by_a_new_token(self):
        expired = {
            "share_token": "stale-token",
            "expires_at": datetime.now(UTC) - timedelta(days=1),
            "revoked_at": None,
        }
        fresh = {"share_token": "fresh-token", "expires_at": None, "revoked_at": None}
        session = _session(_owner_result(), _mapping_result(expired), _mapping_result(fresh))

        state = await ChatRepository(session).create_or_get_shared_chat_token("room-1", 7)

        self.assertEqual(state["share_token"], "fresh-token")
        self.assertFalse(state["is_reused"])

    async def test_force_refresh_rotates_an_active_token(self):
        fresh = {"share_token": "rotated-token", "expires_at": None, "revoked_at": None}
        session = _session(_owner_result(), _mapping_result(fresh))

        state = await ChatRepository(session).create_or_get_shared_chat_token(
            "room-1", 7, force_refresh=True
        )

        self.assertEqual(state["share_token"], "rotated-token")
        self.assertFalse(state["is_reused"])

    async def test_other_user_cannot_create_a_share_link(self):
        session = _session(_owner_result(user_id=99))

        with self.assertRaises(ForbiddenOperationError) as raised:
            await ChatRepository(session).create_or_get_shared_chat_token("room-1", 7)

        self.assertEqual(str(raised.exception), ERROR_CHAT_ROOM_SHARE_FORBIDDEN)
        self.assertEqual(session.execute.await_count, 1)


class RevokeSharedChatTokenTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_revoke_stamps_revoked_at_only_once(self):
        revoked = {
            "share_token": "live-token",
            "expires_at": None,
            "revoked_at": datetime(2026, 9, 13, tzinfo=UTC),
        }
        session = _session(_owner_result(), _mapping_result(revoked))

        state = await ChatRepository(session).revoke_shared_chat_token("room-1", 7)

        self.assertEqual(state, revoked)
        sql = _compile(session.execute.await_args.args[0])
        self.assertIn("UPDATE shared_chat_rooms SET revoked_at=CURRENT_TIMESTAMP", sql)
        self.assertIn("shared_chat_rooms.revoked_at IS NULL", sql)

    async def test_revoking_twice_reports_the_existing_revoked_state(self):
        already = {
            "share_token": "dead-token",
            "expires_at": None,
            "revoked_at": datetime(2026, 9, 1, tzinfo=UTC),
        }
        session = _session(_owner_result(), _mapping_result(None), _mapping_result(already))

        state = await ChatRepository(session).revoke_shared_chat_token("room-1", 7)

        self.assertEqual(state, already)

    async def test_never_shared_room_returns_none(self):
        session = _session(_owner_result(), _mapping_result(None), _mapping_result(None))

        self.assertIsNone(await ChatRepository(session).revoke_shared_chat_token("room-1", 7))

    async def test_other_user_cannot_revoke_a_share_link(self):
        session = _session(_owner_result(user_id=99))

        with self.assertRaises(ForbiddenOperationError) as raised:
            await ChatRepository(session).revoke_shared_chat_token("room-1", 7)

        self.assertEqual(str(raised.exception), ERROR_CHAT_ROOM_SHARE_FORBIDDEN)
        self.assertEqual(session.execute.await_count, 1)

    async def test_missing_room_is_reported_as_not_found(self):
        missing = Mock()
        missing.scalar_one_or_none.return_value = None
        session = _session(missing)

        with self.assertRaises(ResourceNotFoundError):
            await ChatRepository(session).revoke_shared_chat_token("room-1", 7)


if __name__ == "__main__":
    unittest.main()
