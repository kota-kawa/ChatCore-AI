import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.context_vault.routes import (
    api_approve_context_fact_candidate,
    api_create_context_fact,
    api_get_context_extraction_settings,
    api_list_context_fact_candidates,
    api_list_context_facts,
    api_reject_context_fact_candidate,
    api_update_context_fact,
    api_update_context_extraction_settings,
)
from services.api_errors import ApiServiceError
from services.response_models import (
    ContextExtractionSettingsResponse,
    ContextFactCandidateApprovalResponse,
    ContextFactCandidateListResponse,
    ContextFactCandidateResponse,
    ContextFactListResponse,
    ContextFactResponse,
)
from tests.helpers.request_helpers import build_request


def _fact(**overrides):
    payload = {
        "id": 3,
        "fact_type": "preference",
        "title": "Editor",
        "content": "Uses vim",
        "status": "active",
        "revision": 1,
        "source_kind": "manual",
        "importance": 50,
        "created_at": None,
        "updated_at": None,
    }
    payload.update(overrides)
    return ContextFactResponse(**payload)


def _candidate(**overrides):
    payload = {
        "id": 8,
        "fact_type": "project",
        "title": "Chat-Core",
        "content": "Phase 2 candidate",
        "source_kind": "chat",
        "source_ref": "room-123",
        "importance": 80,
        "confidence": 0.9,
        "status": "pending",
        "revision": 1,
        "created_at": None,
        "updated_at": None,
    }
    payload.update(overrides)
    return ContextFactCandidateResponse(**payload)


class ContextVaultRouteTestCase(unittest.TestCase):
    def test_authentication_and_parameter_validation_are_async_safe(self):
        anonymous = build_request(method="GET", path="/api/context-facts", session={})
        self.assertEqual(asyncio.run(api_list_context_facts(anonymous)).status_code, 401)
        request = build_request(
            method="GET", path="/api/context-facts", session={"user_id": 7}
        )
        self.assertEqual(
            asyncio.run(api_list_context_facts(request, fact_type="invalid")).status_code,
            400,
        )

    def test_list_awaits_async_service(self):
        request = build_request(
            method="GET", path="/api/context-facts", session={"user_id": 7}
        )
        result = ContextFactListResponse(facts=[_fact()], total_active=1, next_cursor=None)
        service = AsyncMock(return_value=result)
        with patch("blueprints.context_vault.routes.list_facts", new=service):
            response = asyncio.run(api_list_context_facts(request, limit=20))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body)["facts"][0]["id"], 3)
        service.assert_awaited_once_with(
            7,
            fact_type=None,
            status="active",
            limit=20,
            cursor=None,
        )

    def test_create_and_update_await_service_and_preserve_payload(self):
        create_request = build_request(
            method="POST",
            path="/api/context-facts",
            json_body={
                "fact_type": "preference",
                "title": "Editor",
                "content": "Uses vim",
                "importance": 80,
            },
            session={"user_id": 7},
        )
        create = AsyncMock(return_value=_fact(importance=80))
        with patch("blueprints.context_vault.routes.create_fact", new=create):
            response = asyncio.run(api_create_context_fact(create_request))
        self.assertEqual(response.status_code, 200)
        create.assert_awaited_once_with(
            7,
            fact_type="preference",
            title="Editor",
            content="Uses vim",
            importance=80,
        )

        update_request = build_request(
            method="PUT",
            path="/api/context-facts/3",
            json_body={"revision": 1, "importance": 95},
            session={"user_id": 7},
        )
        update = AsyncMock(return_value=_fact(importance=95, revision=2))
        with patch("blueprints.context_vault.routes.update_fact", new=update):
            response = asyncio.run(api_update_context_fact(update_request, 3))
        self.assertEqual(response.status_code, 200)
        update.assert_awaited_once_with(
            7,
            3,
            expected_revision=1,
            title=None,
            content=None,
            fact_type=None,
            status=None,
            importance=95,
        )

    def test_revision_conflict_is_translated_to_409(self):
        request = build_request(
            method="PUT",
            path="/api/context-facts/3",
            json_body={"revision": 1, "content": "new"},
            session={"user_id": 7},
        )
        with patch(
            "blueprints.context_vault.routes.update_fact",
            new=AsyncMock(side_effect=ApiServiceError("stale", 409, status="fail")),
        ):
            response = asyncio.run(api_update_context_fact(request, 3))
        self.assertEqual(response.status_code, 409)

    def test_candidate_routes_await_list_approve_and_reject(self):
        request = build_request(
            method="GET",
            path="/api/context-facts/candidates",
            session={"user_id": 7},
        )
        listing = AsyncMock(
            return_value=ContextFactCandidateListResponse(
                candidates=[_candidate()], next_cursor=None, total_pending=1
            )
        )
        with patch("blueprints.context_vault.routes.list_candidates", new=listing):
            response = asyncio.run(api_list_context_fact_candidates(request, limit=20))
        self.assertEqual(response.status_code, 200)
        listing.assert_awaited_once_with(7, status="pending", limit=20, cursor=None)

        approve_request = build_request(
            method="PUT",
            path="/api/context-facts/candidates/8/approve",
            json_body={"revision": 1, "title": "Edited", "importance": 95},
            session={"user_id": 7},
        )
        approval = AsyncMock(
            return_value=ContextFactCandidateApprovalResponse(
                candidate=_candidate(status="approved", revision=2),
                fact=_fact(title="Edited", importance=95),
            )
        )
        with patch("blueprints.context_vault.routes.approve_candidate", new=approval):
            response = asyncio.run(api_approve_context_fact_candidate(approve_request, 8))
        self.assertEqual(response.status_code, 200)
        approval.assert_awaited_once_with(
            7,
            8,
            expected_revision=1,
            fact_type=None,
            title="Edited",
            content=None,
            importance=95,
        )

        reject_request = build_request(
            method="PUT",
            path="/api/context-facts/candidates/8/reject",
            json_body={"revision": 1},
            session={"user_id": 7},
        )
        reject = AsyncMock(return_value=_candidate(status="rejected", revision=2))
        with patch("blueprints.context_vault.routes.reject_candidate", new=reject):
            response = asyncio.run(api_reject_context_fact_candidate(reject_request, 8))
        self.assertEqual(response.status_code, 200)
        reject.assert_awaited_once_with(7, 8, expected_revision=1)

    def test_extraction_settings_routes_await_service(self):
        request = build_request(
            method="GET",
            path="/api/context-facts/extraction-settings",
            session={"user_id": 7},
        )
        get_settings = AsyncMock(return_value=ContextExtractionSettingsResponse(enabled=False))
        with patch("blueprints.context_vault.routes.get_extraction_settings", new=get_settings):
            response = asyncio.run(api_get_context_extraction_settings(request))
        self.assertEqual(json.loads(response.body)["enabled"], False)
        get_settings.assert_awaited_once_with(7)

        request = build_request(
            method="PUT",
            path="/api/context-facts/extraction-settings",
            json_body={"enabled": True},
            session={"user_id": 7},
        )
        update_settings = AsyncMock(return_value=ContextExtractionSettingsResponse(enabled=True))
        with patch(
            "blueprints.context_vault.routes.update_extraction_settings",
            new=update_settings,
        ):
            response = asyncio.run(api_update_context_extraction_settings(request))
        self.assertEqual(json.loads(response.body), {"status": "success", "enabled": True})
        update_settings.assert_awaited_once_with(7, True)


if __name__ == "__main__":
    unittest.main()
