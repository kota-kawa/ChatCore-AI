import asyncio
import json
import unittest
from unittest.mock import patch

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
    ContextFactResponse,
)
from tests.helpers.request_helpers import build_request


async def run_blocking_inline(func, *args, **kwargs):
    return func(*args, **kwargs)


def _fact_response(**overrides):
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


def _candidate_response(**overrides):
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
    def test_list_requires_login(self):
        request = build_request(method="GET", path="/api/context-facts", session={})
        response = asyncio.run(api_list_context_facts(request))
        self.assertEqual(response.status_code, 401)

    def test_list_rejects_invalid_fact_type(self):
        request = build_request(
            method="GET", path="/api/context-facts", session={"user_id": 7}
        )
        response = asyncio.run(api_list_context_facts(request, fact_type="bogus"))
        self.assertEqual(response.status_code, 400)

    def test_create_returns_success_payload(self):
        request = build_request(
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
        with (
            patch("blueprints.context_vault.routes.run_blocking", side_effect=run_blocking_inline),
            patch(
                "blueprints.context_vault.routes.create_fact",
                return_value=_fact_response(),
            ) as create,
        ):
            response = asyncio.run(api_create_context_fact(request))

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.body.decode())
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["fact"]["id"], 3)
        self.assertEqual(create.call_args.kwargs["fact_type"], "preference")
        self.assertEqual(create.call_args.kwargs["importance"], 80)

    def test_create_rejects_invalid_payload(self):
        request = build_request(
            method="POST",
            path="/api/context-facts",
            json_body={"fact_type": "unknown", "title": "", "content": ""},
            session={"user_id": 7},
        )
        response = asyncio.run(api_create_context_fact(request))
        self.assertEqual(response.status_code, 400)

    def test_update_surfaces_revision_conflict_as_409(self):
        request = build_request(
            method="PUT",
            path="/api/context-facts/3",
            json_body={"revision": 1, "content": "new"},
            session={"user_id": 7},
        )
        conflict = ApiServiceError("stale", 409, status="fail")
        with (
            patch("blueprints.context_vault.routes.run_blocking", side_effect=run_blocking_inline),
            patch("blueprints.context_vault.routes.update_fact", side_effect=conflict),
        ):
            response = asyncio.run(api_update_context_fact(request, 3))

        self.assertEqual(response.status_code, 409)

    def test_update_passes_importance(self):
        request = build_request(
            method="PUT",
            path="/api/context-facts/3",
            json_body={"revision": 1, "importance": 95},
            session={"user_id": 7},
        )
        with (
            patch("blueprints.context_vault.routes.run_blocking", side_effect=run_blocking_inline),
            patch(
                "blueprints.context_vault.routes.update_fact",
                return_value=_fact_response(importance=95, revision=2),
            ) as update,
        ):
            response = asyncio.run(api_update_context_fact(request, 3))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(update.call_args.kwargs["importance"], 95)

    def test_candidate_list_requires_login_and_rejects_invalid_status(self):
        anonymous = build_request(
            method="GET",
            path="/api/context-facts/candidates",
            session={},
        )
        self.assertEqual(
            asyncio.run(api_list_context_fact_candidates(anonymous)).status_code,
            401,
        )

        authenticated = build_request(
            method="GET",
            path="/api/context-facts/candidates",
            session={"user_id": 7},
        )
        self.assertEqual(
            asyncio.run(
                api_list_context_fact_candidates(authenticated, status="bogus")
            ).status_code,
            400,
        )

    def test_candidate_list_returns_cursor_and_total_pending(self):
        request = build_request(
            method="GET",
            path="/api/context-facts/candidates",
            session={"user_id": 7},
        )
        result = ContextFactCandidateListResponse(
            candidates=[_candidate_response()],
            next_cursor="2026-07-23T12:00:00~8",
            total_pending=4,
        )
        with (
            patch("blueprints.context_vault.routes.run_blocking", side_effect=run_blocking_inline),
            patch(
                "blueprints.context_vault.routes.list_candidates",
                return_value=result,
            ) as list_candidates,
        ):
            response = asyncio.run(api_list_context_fact_candidates(request, limit=20))

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.body.decode())
        self.assertEqual(body["total_pending"], 4)
        self.assertEqual(body["candidates"][0]["id"], 8)
        list_candidates.assert_called_once_with(
            7,
            status="pending",
            limit=20,
            cursor=None,
        )

    def test_approve_candidate_passes_revision_and_edits(self):
        request = build_request(
            method="PUT",
            path="/api/context-facts/candidates/8/approve",
            json_body={
                "revision": 1,
                "title": "Edited",
                "importance": 95,
            },
            session={"user_id": 7},
        )
        result = ContextFactCandidateApprovalResponse(
            candidate=_candidate_response(status="approved", revision=2),
            fact=_fact_response(title="Edited", importance=95),
        )
        with (
            patch("blueprints.context_vault.routes.run_blocking", side_effect=run_blocking_inline),
            patch(
                "blueprints.context_vault.routes.approve_candidate",
                return_value=result,
            ) as approve,
        ):
            response = asyncio.run(api_approve_context_fact_candidate(request, 8))

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.body.decode())
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["fact"]["title"], "Edited")
        approve.assert_called_once_with(
            7,
            8,
            expected_revision=1,
            fact_type=None,
            title="Edited",
            content=None,
            importance=95,
        )

    def test_candidate_review_requires_revision_and_surfaces_conflict(self):
        invalid = build_request(
            method="PUT",
            path="/api/context-facts/candidates/8/reject",
            json_body={},
            session={"user_id": 7},
        )
        self.assertEqual(
            asyncio.run(api_reject_context_fact_candidate(invalid, 8)).status_code,
            400,
        )

        request = build_request(
            method="PUT",
            path="/api/context-facts/candidates/8/reject",
            json_body={"revision": 1},
            session={"user_id": 7},
        )
        with (
            patch("blueprints.context_vault.routes.run_blocking", side_effect=run_blocking_inline),
            patch(
                "blueprints.context_vault.routes.reject_candidate",
                side_effect=ApiServiceError("stale", 409, status="fail"),
            ),
        ):
            response = asyncio.run(api_reject_context_fact_candidate(request, 8))
        self.assertEqual(response.status_code, 409)

    def test_extraction_settings_default_read_and_explicit_update(self):
        get_request = build_request(
            method="GET",
            path="/api/context-facts/extraction-settings",
            session={"user_id": 7},
        )
        with (
            patch("blueprints.context_vault.routes.run_blocking", side_effect=run_blocking_inline),
            patch(
                "blueprints.context_vault.routes.get_extraction_settings",
                return_value=ContextExtractionSettingsResponse(enabled=False),
            ),
        ):
            get_response = asyncio.run(api_get_context_extraction_settings(get_request))
        self.assertFalse(json.loads(get_response.body.decode())["enabled"])

        update_request = build_request(
            method="PUT",
            path="/api/context-facts/extraction-settings",
            json_body={"enabled": True},
            session={"user_id": 7},
        )
        with (
            patch("blueprints.context_vault.routes.run_blocking", side_effect=run_blocking_inline),
            patch(
                "blueprints.context_vault.routes.update_extraction_settings",
                return_value=ContextExtractionSettingsResponse(enabled=True),
            ) as update,
        ):
            update_response = asyncio.run(
                api_update_context_extraction_settings(update_request)
            )
        body = json.loads(update_response.body.decode())
        self.assertEqual(body, {"status": "success", "enabled": True})
        update.assert_called_once_with(7, True)


if __name__ == "__main__":
    unittest.main()
