import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from blueprints.context_vault import context_vault_bp
from blueprints.context_vault.routes import (
    api_export_context_vault,
    api_import_context_vault,
    api_preview_context_vault_import,
)
from services.response_models import (
    ContextVaultImportPreviewResponse,
    ContextVaultImportResponse,
)
from tests.helpers.app_helpers import build_session_test_app
from tests.helpers.request_helpers import build_request


async def _run_blocking_inline(function, *args, **kwargs):
    return function(*args, **kwargs)


class ContextVaultPortabilityRouteTestCase(unittest.TestCase):
    def test_export_requires_login_and_sets_private_download_headers(self):
        anonymous = build_request(
            method="GET",
            path="/api/context-facts/export",
            session={},
        )
        self.assertEqual(
            asyncio.run(api_export_context_vault(anonymous)).status_code,
            401,
        )

        request = build_request(
            method="GET",
            path="/api/context-facts/export",
            session={"user_id": 7},
        )
        with (
            patch(
                "blueprints.context_vault.routes.run_blocking",
                side_effect=_run_blocking_inline,
            ),
            patch(
                "blueprints.context_vault.routes.build_export",
                return_value=(
                    '{"format":"chat-core-personal-context"}',
                    "application/json",
                    "chat-core-context-vault.json",
                ),
            ),
        ):
            response = asyncio.run(api_export_context_vault(request, "json"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="chat-core-context-vault.json"',
        )

    def test_preview_rejects_unknown_wrapper_fields(self):
        request = build_request(
            method="POST",
            path="/api/context-facts/import/preview",
            session={"user_id": 7},
            json_body={
                "format": "json",
                "content": "{}",
                "unexpected": True,
            },
        )
        response = asyncio.run(api_preview_context_vault_import(request))
        self.assertEqual(response.status_code, 400)

    def test_preview_rejects_oversized_wrapper_before_reading_body(self):
        request = build_request(
            method="POST",
            path="/api/context-facts/import/preview",
            session={"user_id": 7},
            json_body={"format": "json", "content": "{}"},
            headers=[(b"content-length", str(33 * 1024 * 1024).encode("ascii"))],
        )
        response = asyncio.run(api_preview_context_vault_import(request))
        self.assertEqual(response.status_code, 413)

    def test_preview_rejects_oversized_stream_without_content_length(self):
        request = build_request(
            method="POST",
            path="/api/context-facts/import/preview",
            session={"user_id": 7},
            raw_body=b'{"format":"json","content":"oversized"}',
        )
        with patch(
            "blueprints.context_vault.routes._MAX_CONTEXT_VAULT_IMPORT_REQUEST_BYTES",
            8,
        ):
            response = asyncio.run(api_preview_context_vault_import(request))
        self.assertEqual(response.status_code, 413)

    def test_preview_and_confirm_return_typed_results(self):
        preview_request = build_request(
            method="POST",
            path="/api/context-facts/import/preview",
            session={"user_id": 7},
            json_body={"format": "json", "content": "{}"},
        )
        preview_result = ContextVaultImportPreviewResponse(
            preview_token="signed",
            total_count=1,
            active_count=1,
            deprecated_count=0,
            duplicate_count=0,
            importable_count=1,
            can_import=True,
            sample_facts=[],
            warnings=[],
            expires_at="2026-07-23T00:15:00+00:00",
        )
        with (
            patch(
                "blueprints.context_vault.routes.run_blocking",
                side_effect=_run_blocking_inline,
            ),
            patch(
                "blueprints.context_vault.routes.preview_import",
                return_value=preview_result,
            ),
        ):
            preview_response = asyncio.run(
                api_preview_context_vault_import(preview_request)
            )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(
            json.loads(preview_response.body.decode())["preview_token"],
            "signed",
        )

        confirm_request = build_request(
            method="POST",
            path="/api/context-facts/import",
            session={"user_id": 7},
            json_body={
                "format": "json",
                "content": "{}",
                "preview_token": "signed",
            },
        )
        result = ContextVaultImportResponse(
            imported_count=1,
            skipped_duplicate_count=0,
            active_count=1,
            deprecated_count=0,
        )
        with (
            patch(
                "blueprints.context_vault.routes.run_blocking",
                side_effect=_run_blocking_inline,
            ),
            patch(
                "blueprints.context_vault.routes.confirm_import",
                return_value=result,
            ),
        ):
            response = asyncio.run(api_import_context_vault(confirm_request))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode())["imported_count"], 1)

    def test_import_endpoints_require_csrf(self):
        app = build_session_test_app(context_vault_bp)

        async def scenario():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.post(
                    "/api/context-facts/import/preview",
                    json={"format": "json", "content": "{}"},
                )

        response = asyncio.run(scenario())
        self.assertEqual(response.status_code, 403)
        self.assertIn("CSRF", response.json().get("detail", ""))


if __name__ == "__main__":
    unittest.main()
