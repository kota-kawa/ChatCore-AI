"""記憶の完全な削除のルート(DELETE /api/context-facts/{id}、DELETE /api/context-facts)の認証・入力の検証（revision、確認の値）・
サービスへの引き渡し・エラーの変換を検証し、失敗の記録に記憶の文面や例外のトレースを残さないことを確かめるテスト。

Tests the permanent-delete routes (DELETE /api/context-facts/{id} and DELETE /api/context-facts): authentication, input validation
(revision, confirmation value), delegation and error translation, and that a failure is logged without memory wording or an
exception traceback.
"""

import asyncio
import json
import logging
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import IntegrityError

from blueprints.context_vault.constants import DELETE_ALL_CONFIRMATION
from blueprints.context_vault.routes import api_delete_all_context_facts, api_delete_context_fact, context_vault_bp
from services.api_errors import ApiServiceError, ResourceNotFoundError
from tests.helpers.request_helpers import build_request


class DeleteRoutesTestCase(unittest.TestCase):
    def _delete_one(self, *, session=None, revision=2, service=None):
        request = build_request(method="DELETE", path="/api/context-facts/4", session={"user_id": 7} if session is None else session)
        service = service or AsyncMock(return_value=None)
        with patch("blueprints.context_vault.routes.delete_fact", new=service):
            response = asyncio.run(api_delete_context_fact(request, 4, revision=revision))
        return response, service

    def _delete_all(self, *, session=None, confirm=DELETE_ALL_CONFIRMATION, service=None):
        request = build_request(method="DELETE", path="/api/context-facts", session={"user_id": 7} if session is None else session)
        service = service or AsyncMock(return_value=3)
        with patch("blueprints.context_vault.routes.delete_all_facts", new=service):
            response = asyncio.run(api_delete_all_context_facts(request, confirm=confirm))
        return response, service

    def test_delete_one_passes_the_owner_and_revision(self):
        response, service = self._delete_one()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body), {"status": "success"})
        service.assert_awaited_once_with(7, 4, expected_revision=2)

    def test_delete_one_requires_login_and_a_positive_revision(self):
        response, service = self._delete_one(session={})
        self.assertEqual(response.status_code, 401)
        service.assert_not_awaited()
        for revision in (None, 0, -1):
            with self.subTest(revision=revision):
                response, service = self._delete_one(revision=revision)
                self.assertEqual(response.status_code, 400)
                service.assert_not_awaited()

    def test_delete_one_translates_not_found_and_conflict(self):
        for error, status in ((ResourceNotFoundError("none"), 404), (ApiServiceError("conflict", 409, status="fail"), 409)):
            with self.subTest(status=status):
                response, _ = self._delete_one(service=AsyncMock(side_effect=error))
                self.assertEqual(response.status_code, status)

    def test_delete_all_needs_the_confirmation_value(self):
        response, service = self._delete_all()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body), {"status": "success", "deleted_count": 3})
        service.assert_awaited_once_with(7)
        for confirm in (None, "", "yes", "DELETE-ALL", "true"):
            with self.subTest(confirm=confirm):
                response, service = self._delete_all(confirm=confirm)
                self.assertEqual(response.status_code, 400)
                service.assert_not_awaited()

    def test_delete_all_requires_login_and_only_touches_the_session_owner(self):
        response, service = self._delete_all(session={})
        self.assertEqual(response.status_code, 401)
        service.assert_not_awaited()
        _, service = self._delete_all(session={"user_id": 12})
        service.assert_awaited_once_with(12)

    def test_delete_failures_are_logged_without_the_exception_or_its_parameters(self):
        secret = "秘密の記憶の文面"
        boom = IntegrityError("DELETE ...", {"content": secret}, Exception("boom"))
        for call in (
            lambda: self._delete_one(service=AsyncMock(side_effect=boom)),
            lambda: self._delete_all(service=AsyncMock(side_effect=boom)),
        ):
            with self.assertLogs("blueprints.context_vault", level=logging.ERROR) as logs:
                response, _ = call()
            self.assertEqual(response.status_code, 500)
            self.assertNotIn(secret, response.body.decode())
            self.assertIsNone(logs.records[0].exc_info)
            self.assertNotIn(secret, str(logs.records[0].__dict__))


class RouteRegistrationTestCase(unittest.TestCase):
    def test_the_routes_are_registered_as_deletes(self):
        routes = {(route.path, tuple(sorted(route.methods))) for route in context_vault_bp.routes}
        self.assertIn(("/api/context-facts/{fact_id:int}", ("DELETE",)), routes)
        self.assertIn(("/api/context-facts", ("DELETE",)), routes)


if __name__ == "__main__":
    unittest.main()
