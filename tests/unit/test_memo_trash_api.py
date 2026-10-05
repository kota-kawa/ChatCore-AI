import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.exc import SQLAlchemyError

from blueprints.memo import memo_bp
from services.api_errors import ResourceNotFoundError
from services.csrf import CSRF_HEADER_NAME, CSRF_SESSION_KEY
from services.repositories.memo_constants import MEMO_TRASH_RETENTION_DAYS
from services.repositories.memo_repository import (
    bulk_action,
    delete_memo,
    empty_memo_trash,
    fetch_memo_summaries,
    purge_expired_memo_trash,
    purge_memo,
    restore_memo,
)
from services.repositories.memo_serializers import serialize_memo_detail, serialize_memo_summary
from services.request_models import MemoBulkActionRequest
from tests.helpers.app_helpers import build_session_test_app

CSRF_TOKEN = "trash-test-csrf"


def _sql(statement) -> str:
    return " ".join(str(statement.compile(dialect=dialect())).split())


class MemoTrashRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = build_session_test_app(memo_bp, include_test_session_route=True)

    def _request(self, method: str, path: str, *, logged_in: bool = True, csrf: bool = True, json=None):
        async def scenario():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app), base_url="http://testserver"
            ) as client:
                session = {CSRF_SESSION_KEY: CSRF_TOKEN}
                if logged_in:
                    session["user_id"] = 7
                await client.post("/_test/session", json=session)
                headers = {CSRF_HEADER_NAME: CSRF_TOKEN} if csrf else {}
                return await client.request(method, path, headers=headers, json=json)

        return asyncio.run(scenario())

    def test_restore_returns_the_restored_memo(self):
        with patch("blueprints.memo._restore_memo", new=AsyncMock(return_value={"id": 10, "deleted_at": None})) as restore:
            response = self._request("POST", "/memo/api/10/restore")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "success", "memo": {"id": 10, "deleted_at": None}})
        restore.assert_awaited_once_with(7, 10)

    def test_restore_of_a_memo_outside_the_trash_is_not_found(self):
        with patch("blueprints.memo._restore_memo", new=AsyncMock(side_effect=ResourceNotFoundError("メモが見つかりません。"))):
            response = self._request("POST", "/memo/api/10/restore")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["status"], "fail")

    def test_purge_one_memo_and_not_found_outside_the_trash(self):
        with patch("blueprints.memo._purge_memo", new=AsyncMock(return_value=None)) as purge:
            response = self._request("DELETE", "/memo/api/trash/10")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "success"})
        purge.assert_awaited_once_with(7, 10)

        with patch("blueprints.memo._purge_memo", new=AsyncMock(side_effect=ResourceNotFoundError("メモが見つかりません。"))):
            response = self._request("DELETE", "/memo/api/trash/10")
        self.assertEqual(response.status_code, 404)

    def test_empty_trash_deletes_only_the_signed_in_users_memos(self):
        with patch("blueprints.memo._empty_memo_trash", new=AsyncMock(return_value=3)) as empty:
            response = self._request("DELETE", "/memo/api/trash")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "success", "deleted": 3})
        empty.assert_awaited_once_with(7)

    def test_trash_routes_require_login_and_csrf(self):
        routes = (("POST", "/memo/api/10/restore"), ("DELETE", "/memo/api/trash/10"), ("DELETE", "/memo/api/trash"))
        for method, path in routes:
            with self.subTest(path=path, check="login"):
                self.assertEqual(self._request(method, path, logged_in=False).status_code, 401)
            with self.subTest(path=path, check="csrf"):
                self.assertEqual(self._request(method, path, csrf=False).status_code, 403)

    def test_trash_routes_report_database_failures_as_server_errors(self):
        failure = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with patch("blueprints.memo._restore_memo", new=failure):
            self.assertEqual(self._request("POST", "/memo/api/10/restore").status_code, 500)
        with patch("blueprints.memo._purge_memo", new=failure):
            self.assertEqual(self._request("DELETE", "/memo/api/trash/10").status_code, 500)
        with patch("blueprints.memo._empty_memo_trash", new=failure):
            self.assertEqual(self._request("DELETE", "/memo/api/trash").status_code, 500)

    def test_recent_lists_the_trash_with_only_trashed_and_skips_the_semantic_query(self):
        summaries = AsyncMock(return_value={"total": 0, "memos": []})
        generate = MagicMock(return_value=[0.1])
        with patch("blueprints.memo._fetch_memo_summaries", new=summaries), patch(
            "blueprints.memo.embeddings_available", return_value=True
        ), patch("blueprints.memo.generate_embedding", new=generate):
            response = self._request("GET", "/memo/api/recent?only_trashed=true&sort=semantic&q=abc")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(summaries.await_args.kwargs["only_trashed"])
        self.assertIsNone(summaries.await_args.kwargs["semantic_query_embedding"])
        generate.assert_not_called()

    def test_recent_defaults_to_the_live_list(self):
        summaries = AsyncMock(return_value={"total": 0, "memos": []})
        with patch("blueprints.memo._fetch_memo_summaries", new=summaries):
            self._request("GET", "/memo/api/recent")

        self.assertFalse(summaries.await_args.kwargs["only_trashed"])

    def test_bulk_accepts_restore_and_purge(self):
        for action in ("delete", "restore", "purge"):
            with self.subTest(action=action):
                self.assertEqual(MemoBulkActionRequest(action=action, memo_ids=[1]).action, action)
        with patch("blueprints.memo._bulk_action", new=AsyncMock(return_value={"affected": 2})) as bulk:
            response = self._request("POST", "/memo/api/bulk", json={"action": "restore", "memo_ids": [1, 2]})
        self.assertEqual(response.json(), {"status": "success", "affected": 2})
        self.assertEqual(bulk.await_args.args[:3], (7, "restore", [1, 2]))


class MemoTrashRepositoryStatementsTestCase(unittest.IsolatedAsyncioTestCase):
    def _session(self, *, scalar=0, scalars=(), rows=()):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=scalar)
        result = MagicMock()
        result.mappings.return_value.all.return_value = list(rows)
        result.scalar_one_or_none.return_value = 1 if scalars else None
        result.scalars.return_value.all.return_value = list(scalars)
        session.execute = AsyncMock(return_value=result)
        session.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=list(scalars))))
        return session

    async def _summaries(self, session, **overrides):
        options = {
            "limit": 10,
            "offset": 0,
            "query": "",
            "date_from": "",
            "date_to": "",
            "sort": "recent",
            "include_archived": False,
            "only_archived": False,
            "pinned_first": True,
            "collection_id": None,
            "semantic_query_embedding": None,
            "session": session,
        }
        options.update(overrides)
        return await fetch_memo_summaries(7, **options)

    async def test_live_and_semantic_lists_exclude_trashed_memos(self):
        for overrides in ({}, {"semantic_query_embedding": [0.1, 0.2]}):
            with self.subTest(overrides=overrides):
                session = self._session()
                await self._summaries(session, **overrides)
                for statement in (session.scalar.await_args.args[0], session.execute.await_args.args[0]):
                    self.assertIn("memo_entries.deleted_at IS NULL", _sql(statement))

    async def test_trash_list_shows_only_trashed_memos_newest_deleted_first(self):
        session = self._session()
        result = await self._summaries(session, only_trashed=True, sort="title", include_archived=False)

        self.assertEqual(result, {"total": 0, "memos": []})
        for statement in (session.scalar.await_args.args[0], session.execute.await_args.args[0]):
            self.assertIn("memo_entries.deleted_at IS NOT NULL", _sql(statement))
        listing = _sql(session.execute.await_args.args[0])
        self.assertIn("ORDER BY memo_entries.deleted_at DESC, memo_entries.id DESC", listing)
        self.assertNotIn("archived_at IS NULL", listing.split("WHERE", 1)[1])

    async def test_trash_list_ignores_a_semantic_embedding(self):
        session = self._session()
        await self._summaries(session, only_trashed=True, query="abc", semantic_query_embedding=[0.1, 0.2])

        self.assertNotIn("<=>", _sql(session.execute.await_args.args[0]))
        self.assertIn("ILIKE", _sql(session.execute.await_args.args[0]))

    async def test_delete_moves_a_live_memo_to_the_trash_instead_of_deleting_it(self):
        session = self._session(scalars=[10])
        await delete_memo(7, 10, session=session)

        statement = _sql(session.execute.await_args_list[0].args[0])
        self.assertTrue(statement.startswith("UPDATE memo_entries SET deleted_at=CURRENT_TIMESTAMP"))
        self.assertIn("memo_entries.deleted_at IS NULL", statement)
        # 共有は同じトランザクションで解除する
        # Sharing is revoked in the same transaction.
        revoke = _sql(session.execute.await_args_list[1].args[0])
        self.assertTrue(revoke.startswith("UPDATE shared_memo_entries SET revoked_at=CURRENT_TIMESTAMP"))
        self.assertIn("shared_memo_entries.revoked_at IS NULL", revoke)

    async def test_delete_of_a_missing_or_trashed_memo_is_not_found(self):
        with self.assertRaises(ResourceNotFoundError):
            await delete_memo(7, 10, session=self._session())

    async def test_restore_and_purge_only_touch_trashed_memos(self):
        restore_session = self._session(scalars=[10])
        with patch("services.repositories.memo_repository.fetch_memo_detail", new=AsyncMock(return_value={"id": 10})):
            await restore_memo(7, 10, session=restore_session)
        restore_statement = restore_session.execute.await_args.args[0]
        statement = _sql(restore_statement)
        self.assertTrue(statement.startswith("UPDATE memo_entries SET deleted_at="))
        self.assertIsNone(restore_statement.compile(dialect=dialect()).params["deleted_at"])
        self.assertIn("memo_entries.deleted_at IS NOT NULL", statement)

        purge_session = self._session(scalars=[10])
        await purge_memo(7, 10, session=purge_session)
        statement = _sql(purge_session.execute.await_args.args[0])
        self.assertTrue(statement.startswith("DELETE FROM memo_entries"))
        self.assertIn("memo_entries.deleted_at IS NOT NULL", statement)

        for operation in (restore_memo, purge_memo):
            with self.assertRaises(ResourceNotFoundError):
                await operation(7, 10, session=self._session())

    async def test_empty_trash_is_scoped_to_one_user(self):
        session = self._session(scalars=[1, 2])
        self.assertEqual(await empty_memo_trash(7, session=session), 2)

        statement = session.execute.await_args.args[0]
        compiled = statement.compile(dialect=dialect())
        self.assertIn("memo_entries.user_id =", str(compiled))
        self.assertIn("memo_entries.deleted_at IS NOT NULL", str(compiled))
        self.assertIn(7, compiled.params.values())

    async def test_expiry_purge_uses_the_retention_constant(self):
        session = self._session(scalars=[1])
        self.assertEqual(await purge_expired_memo_trash(limit=25, session=session), 1)

        compiled = session.execute.await_args.args[0].compile(dialect=dialect())
        self.assertIn("memo_entries.deleted_at <=", str(compiled))
        # 1回の削除は件数を絞ったバッチで、古い順
        # One delete is a bounded batch, oldest first.
        self.assertIn("LIMIT", str(compiled))
        self.assertIn("ORDER BY memo_entries.deleted_at, memo_entries.id", str(compiled))
        self.assertIn(25, compiled.params.values())
        self.assertEqual(MEMO_TRASH_RETENTION_DAYS, 30)
        self.assertTrue(any(getattr(v, "days", None) == MEMO_TRASH_RETENTION_DAYS for v in compiled.params.values()))

    async def test_bulk_actions_pick_the_scope_by_action(self):
        for action, expected in (
            ("archive", "memo_entries.deleted_at IS NULL"),
            ("delete", "memo_entries.deleted_at IS NULL"),
            ("restore", "memo_entries.deleted_at IS NOT NULL"),
            ("purge", "memo_entries.deleted_at IS NOT NULL"),
        ):
            with self.subTest(action=action):
                session = self._session(scalars=[10])
                await bulk_action(7, action, [10], collection_id=None, session=session)
                selection = _sql(session.scalars.await_args.args[0])
                change = _sql(session.execute.await_args_list[0].args[0])
                self.assertIn(expected, selection)
                self.assertIn(expected, change)
                self.assertEqual(change.split(" ", 1)[0], "DELETE" if action == "purge" else "UPDATE")
                # 共有の解除はゴミ箱へ移す delete のときだけ
                # Share revocation happens only for delete (moving to the trash).
                revoked = any("shared_memo_entries" in _sql(call.args[0]) for call in session.execute.await_args_list)
                self.assertEqual(revoked, action == "delete")


class MemoTrashSerializationTestCase(unittest.TestCase):
    def test_summary_and_detail_carry_the_deletion_time_and_purge_time(self):
        deleted_at = datetime(2026, 10, 1, 9, 0)
        for serialize in (serialize_memo_summary, serialize_memo_detail):
            with self.subTest(serialize=serialize.__name__):
                payload = serialize({"id": 1, "deleted_at": deleted_at})
                self.assertEqual(payload["deleted_at"], "2026-10-01T09:00:00")
                self.assertEqual(payload["trash_expires_at"], "2026-10-31T09:00:00")

    def test_live_memos_have_no_deletion_time(self):
        payload = serialize_memo_summary({"id": 1})
        self.assertIsNone(payload["deleted_at"])
        self.assertIsNone(payload["trash_expires_at"])


if __name__ == "__main__":
    unittest.main()
