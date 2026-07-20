import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.context_vault.routes import (
    api_create_context_fact,
    api_list_context_facts,
    api_update_context_fact,
)
from services.api_errors import ApiServiceError
from services.response_models import ContextFactResponse
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


if __name__ == "__main__":
    unittest.main()
