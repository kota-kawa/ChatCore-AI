"""置き換えを元に戻すルート(POST /api/context-facts/{id}/revert-replacement)の認証・入力の検証・サービスへの引き渡し・エラーの変換を検証し、
失敗の記録に記憶の文面や例外のトレースを残さないことを確かめるテスト。

Tests the undo-replacement route (POST /api/context-facts/{id}/revert-replacement): authentication, input validation, delegation and error
translation, and that a failure is logged without memory wording or an exception traceback.
"""

import asyncio
import json
import logging
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import IntegrityError

from blueprints.context_vault.routes import api_revert_context_fact_replacement, context_vault_bp
from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.response_models import ContextFactResponse, ContextFactRevertReplacementResponse
from tests.helpers.request_helpers import build_request


def _fact(fact_id, **overrides):
    payload = {
        "id": fact_id,
        "fact_type": "profile",
        "title": "住所",
        "content": "東京に住んでいる",
        "status": "active",
        "revision": 1,
        "source_kind": "chat",
        "importance": 50,
    }
    payload.update(overrides)
    return ContextFactResponse(**payload)


class RevertReplacementRouteTestCase(unittest.TestCase):
    def _call(self, *, session=None, body=None, service=None):
        request = build_request(
            method="POST",
            path="/api/context-facts/4/revert-replacement",
            session={"user_id": 7} if session is None else session,
            json_body={"revision": 2} if body is None else body,
        )
        service = service or AsyncMock()
        with patch("blueprints.context_vault.routes.revert_replacement", new=service):
            response = asyncio.run(api_revert_context_fact_replacement(request, 4))
        return response, service

    def test_returns_both_facts(self):
        service = AsyncMock(
            return_value=ContextFactRevertReplacementResponse(
                fact=_fact(4, status="deprecated", revision=3),
                restored_fact=_fact(3, revision=6, title="旧住所"),
            )
        )
        response, service = self._call(service=service)
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.body)
        self.assertEqual(body["status"], "success")
        self.assertEqual((body["fact"]["id"], body["fact"]["status"]), (4, "deprecated"))
        self.assertEqual((body["restored_fact"]["id"], body["restored_fact"]["status"]), (3, "active"))
        service.assert_awaited_once_with(7, 4, expected_revision=2)

    def test_login_and_revision_are_required(self):
        response, service = self._call(session={})
        self.assertEqual(response.status_code, 401)
        service.assert_not_awaited()
        for body in ({}, {"revision": 0}, {"revision": "x"}):
            with self.subTest(body=body):
                response, service = self._call(body=body)
                self.assertEqual(response.status_code, 400)
                service.assert_not_awaited()

    def test_not_found_and_conflict_are_translated(self):
        for error, status in (
            (ResourceNotFoundError("none"), 404),
            (ApiServiceError("conflict", 409, status="fail"), 409),
        ):
            with self.subTest(status=status):
                response, _ = self._call(service=AsyncMock(side_effect=error))
                self.assertEqual(response.status_code, status)

    def test_unexpected_failure_is_logged_without_the_exception_or_its_parameters(self):
        secret = "東京に住んでいる(記憶の文面)"
        boom = IntegrityError("UPDATE context_facts ...", {"content": secret}, Exception("boom"))
        with self.assertLogs("blueprints.context_vault", level=logging.ERROR) as logs:
            response, _ = self._call(service=AsyncMock(side_effect=boom))
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(secret, response.body.decode())
        record = logs.records[0]
        self.assertIsNone(record.exc_info)
        self.assertNotIn(secret, record.getMessage())
        self.assertNotIn(secret, str(record.__dict__))
        self.assertEqual(record.error_type, "IntegrityError")


class RouteRegistrationTestCase(unittest.TestCase):
    def test_the_route_is_registered_as_a_post(self):
        routes = {(route.path, tuple(sorted(route.methods))) for route in context_vault_bp.routes}
        self.assertIn(("/api/context-facts/{fact_id:int}/revert-replacement", ("POST",)), routes)


if __name__ == "__main__":
    unittest.main()
