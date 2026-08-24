import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.api_errors import ApiServiceError
from services.context_vault_portability import (
    CONTEXT_VAULT_FORMAT,
    CONTEXT_VAULT_FORMAT_VERSION,
    build_export,
    confirm_import,
    parse_import_document,
    preview_import,
)


def _row(**overrides):
    row = {
        "id": 3,
        "user_id": 7,
        "fact_type": "preference",
        "title": "Editor",
        "content": "Uses Vim",
        "source_kind": "mcp",
        "source_ref": "private",
        "source_client_id": "internal-client",
        "importance": 80,
        "status": "active",
        "revision": 4,
        "created_at": "2026-07-23T00:00:00",
        "updated_at": "2026-07-23T01:00:00",
    }
    row.update(overrides)
    return row


def _json_document(facts):
    return json.dumps(
        {
            "format": CONTEXT_VAULT_FORMAT,
            "version": CONTEXT_VAULT_FORMAT_VERSION,
            "exported_at": "2026-07-23T00:00:00+00:00",
            "facts": facts,
        },
        ensure_ascii=False,
    )


class ContextVaultPortabilityParsingTestCase(unittest.TestCase):
    def test_markdown_round_trip_preserves_untrusted_title(self):
        fact = {
            "fact_type": "preference",
            "title": "Editor\nPreference ![remote](https://example.test/x)",
            "content": "Uses Vim",
            "status": "active",
            "importance": 80,
        }
        from services.context_vault_portability import _escape_markdown_heading

        content = (
            "<!-- chat-core-context-vault-version: 1 -->\n"
            "\n```context-fact\n"
            f"{json.dumps(fact, ensure_ascii=False)}\n```\n"
        )
        parsed = parse_import_document("markdown", content)
        self.assertEqual(parsed[0].title, fact["title"])
        self.assertIn(r"Editor Preference", _escape_markdown_heading(fact["title"]))

    def test_import_rejects_bad_version_unknown_fields_and_invalid_text(self):
        valid = {
            "fact_type": "profile",
            "title": "Name",
            "content": "Kota",
            "status": "active",
            "importance": 50,
        }
        cases = [
            {**json.loads(_json_document([valid])), "version": 2},
            {**json.loads(_json_document([valid])), "unexpected": True},
            json.loads(_json_document([{**valid, "id": 99}])),
            json.loads(_json_document([{**valid, "title": " "}])),
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ApiServiceError):
                    parse_import_document("json", json.dumps(payload))

    def test_import_enforces_size_and_fact_count_limits(self):
        valid = {
            "fact_type": "profile",
            "title": "Name",
            "content": "Kota",
            "status": "active",
            "importance": 50,
        }
        with patch("services.context_vault_portability.MAX_CONTEXT_VAULT_IMPORT_BYTES", 4):
            with self.assertRaises(ApiServiceError) as error:
                parse_import_document("json", "ああ")
        self.assertEqual(error.exception.status_code, 413)
        with self.assertRaises(ApiServiceError) as error:
            parse_import_document("json", _json_document([valid] * 1001))
        self.assertEqual(error.exception.status_code, 413)


class ContextVaultPortabilityDatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_json_export_uses_async_repository_and_excludes_internal_fields(self):
        repo = MagicMock()
        repo.list_all_facts = AsyncMock(return_value=[_row(), _row(id=4, status="deprecated")])
        with patch("services.context_vault_portability._repository", return_value=repo):
            content, media_type, filename = await build_export(
                7, "json", session=object()
            )
        payload = json.loads(content)
        self.assertEqual(payload["format"], CONTEXT_VAULT_FORMAT)
        self.assertEqual(len(payload["facts"]), 2)
        for internal in ("id", "user_id", "revision", "source_kind", "source_ref"):
            self.assertNotIn(internal, payload["facts"][0])
        self.assertEqual(media_type, "application/json")
        self.assertEqual(filename, "chat-core-context-vault.json")
        repo.list_all_facts.assert_awaited_once_with(7, limit=1001)

    async def test_preview_uses_async_duplicate_and_cap_queries(self):
        fact = {
            "fact_type": "profile",
            "title": "Name",
            "content": "Kota",
            "status": "active",
            "importance": 50,
        }
        repo = MagicMock()
        repo.find_existing_portable_signatures = AsyncMock(return_value=set())
        repo.count_active = AsyncMock(return_value=200)
        with patch("services.context_vault_portability._repository", return_value=repo), patch(
            "services.context_vault_portability.get_session_secret_key",
            return_value="test-secret",
        ):
            result = await preview_import(7, "json", _json_document([fact]), session=object())
        self.assertEqual(result.importable_count, 1)
        self.assertFalse(result.can_import)
        repo.find_existing_portable_signatures.assert_awaited_once()
        repo.count_active.assert_awaited_once_with(7)

    async def test_confirm_import_is_atomic_at_service_boundary_and_schedules_active_only(self):
        facts = [
            {
                "fact_type": "profile",
                "title": "Name",
                "content": "Kota",
                "status": "active",
                "importance": 50,
            },
            {
                "fact_type": "reference",
                "title": "Old",
                "content": "Archived",
                "status": "deprecated",
                "importance": 10,
            },
        ]
        content = _json_document(facts)
        repo = MagicMock()
        repo.find_existing_portable_signatures = AsyncMock(return_value=set())
        repo.count_active = AsyncMock(return_value=0)
        repo.bulk_import_facts = AsyncMock(
            return_value={
                "facts": [
                    _row(id=11, fact_type="profile", title="Name", content="Kota"),
                    _row(
                        id=12,
                        fact_type="reference",
                        title="Old",
                        content="Archived",
                        status="deprecated",
                    ),
                ],
                "skipped_duplicate_count": 0,
                "active_count": 1,
                "deprecated_count": 1,
            }
        )
        with patch("services.context_vault_portability._repository", return_value=repo), patch(
            "services.context_vault_portability.get_session_secret_key",
            return_value="test-secret",
        ), patch("services.context_vault_portability.schedule_embedding") as schedule:
            preview = await preview_import(7, "json", content, session=object())
            result = await confirm_import(
                7,
                "json",
                content,
                preview.preview_token,
                session=object(),
            )
        self.assertEqual(result.imported_count, 2)
        repo.bulk_import_facts.assert_awaited_once()
        schedule.assert_called_once()
        self.assertEqual(schedule.call_args.args[0], 11)

    async def test_confirm_rejects_tampered_preview_without_repository_call(self):
        fact = {
            "fact_type": "profile",
            "title": "Name",
            "content": "Kota",
            "status": "active",
            "importance": 50,
        }
        repo = MagicMock()
        repo.bulk_import_facts = AsyncMock()
        with patch("services.context_vault_portability._repository", return_value=repo), patch(
            "services.context_vault_portability.get_session_secret_key",
            return_value="test-secret",
        ):
            with self.assertRaises(ApiServiceError):
                await confirm_import(
                    7,
                    "json",
                    _json_document([fact]),
                    "tampered",
                    session=object(),
                )
        repo.bulk_import_facts.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
