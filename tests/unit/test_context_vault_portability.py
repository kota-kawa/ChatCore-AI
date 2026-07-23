import json
import unittest
from unittest.mock import MagicMock, patch

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
        "source_client_id": "client-secret",
        "importance": 80,
        "idempotency_key_hash": "a" * 64,
        "idempotency_payload_hash": "b" * 64,
        "status": "active",
        "revision": 4,
        "embedding_vector": [0.1],
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


class ContextVaultPortabilityTestCase(unittest.TestCase):
    def _patch_repo(self, repo):
        return patch(
            "services.context_vault_portability._repository",
            return_value=repo,
        )

    def test_json_export_is_complete_and_excludes_internal_fields(self):
        repo = MagicMock()
        repo.list_all_facts.return_value = [
            _row(),
            _row(id=4, status="deprecated", title="Old"),
        ]
        with self._patch_repo(repo):
            content, media_type, filename = build_export(7, "json")

        payload = json.loads(content)
        self.assertEqual(payload["format"], CONTEXT_VAULT_FORMAT)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["facts"]), 2)
        self.assertEqual(payload["facts"][1]["status"], "deprecated")
        for internal in (
            "id",
            "user_id",
            "revision",
            "source_kind",
            "source_ref",
            "source_client_id",
            "created_at",
            "updated_at",
            "embedding_vector",
            "idempotency_key_hash",
        ):
            self.assertNotIn(internal, payload["facts"][0])
        self.assertEqual(media_type, "application/json")
        self.assertEqual(filename, "chat-core-context-vault.json")
        repo.list_all_facts.assert_called_once_with(7, limit=1001)

    def test_markdown_export_round_trips_and_includes_human_heading(self):
        repo = MagicMock()
        repo.list_all_facts.return_value = [
            _row(title="Editor\nPreference ![remote](https://example.test/x)")
        ]
        with self._patch_repo(repo):
            content, media_type, filename = build_export(7, "markdown")

        facts = parse_import_document("markdown", content)
        self.assertEqual(
            facts[0].title,
            "Editor\nPreference ![remote](https://example.test/x)",
        )
        self.assertIn(
            r"## Editor Preference \!\[remote\]\(https://example\.test/x\)",
            content,
        )
        self.assertIn("Type: `preference`", content)
        self.assertTrue(media_type.startswith("text/markdown"))
        self.assertEqual(filename, "chat-core-context-vault.md")

    def test_markdown_requires_exactly_one_standalone_version_marker(self):
        portable = {
            "fact_type": "profile",
            "title": "<!-- chat-core-context-vault-version: 1 -->",
            "content": "Kota",
            "status": "active",
            "importance": 50,
        }
        block = f"```context-fact\n{json.dumps(portable)}\n```"
        with self.assertRaises(ApiServiceError):
            parse_import_document("markdown", block)
        with self.assertRaises(ApiServiceError):
            parse_import_document(
                "markdown",
                "<!-- chat-core-context-vault-version: 1 -->\n"
                "<!-- chat-core-context-vault-version: 1 -->\n"
                f"{block}",
            )

    def test_markdown_import_accepts_crlf_export(self):
        repo = MagicMock()
        repo.list_all_facts.return_value = [_row()]
        with self._patch_repo(repo):
            content, _, _ = build_export(7, "markdown")
        facts = parse_import_document("markdown", content.replace("\n", "\r\n"))
        self.assertEqual(len(facts), 1)

    def test_import_rejects_unknown_root_and_fact_fields_and_wrong_version(self):
        valid_fact = {
            "fact_type": "profile",
            "title": "Name",
            "content": "Kota",
            "status": "active",
            "importance": 50,
        }
        cases = [
            {**json.loads(_json_document([valid_fact])), "version": 2},
            {**json.loads(_json_document([valid_fact])), "unexpected": True},
            json.loads(_json_document([{**valid_fact, "id": 99}])),
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ApiServiceError) as error:
                    parse_import_document("json", json.dumps(payload))
                self.assertEqual(error.exception.status_code, 400)

    def test_import_rejects_blank_text_and_oversized_utf8(self):
        blank = {
            "fact_type": "profile",
            "title": " ",
            "content": "Kota",
            "status": "active",
            "importance": 50,
        }
        with self.assertRaises(ApiServiceError):
            parse_import_document("json", _json_document([blank]))
        with patch(
            "services.context_vault_portability.MAX_CONTEXT_VAULT_IMPORT_BYTES",
            4,
        ):
            with self.assertRaises(ApiServiceError) as error:
                parse_import_document("json", "ああ")
        self.assertEqual(error.exception.status_code, 413)

    def test_import_rejects_unpaired_surrogates_and_nul(self):
        template = (
            '{"format":"chat-core-personal-context","version":1,'
            '"exported_at":"2026-07-23T00:00:00Z","facts":['
            '{"fact_type":"profile","title":"%s","content":"Kota",'
            '"status":"active","importance":50}]}'
        )
        for encoded_title in (r"\ud800", r"\u0000"):
            with self.subTest(encoded_title=encoded_title):
                with self.assertRaises(ApiServiceError) as error:
                    parse_import_document("json", template % encoded_title)
                self.assertEqual(error.exception.status_code, 400)

    def test_export_rejects_more_than_round_trip_limit(self):
        repo = MagicMock()
        repo.list_all_facts.return_value = [_row()] * 1001
        with self._patch_repo(repo):
            with self.assertRaises(ApiServiceError) as error:
                build_export(7, "json")
        self.assertEqual(error.exception.status_code, 409)

    def test_import_rejects_more_than_fact_limit(self):
        fact = {
            "fact_type": "profile",
            "title": "Name",
            "content": "Kota",
            "status": "deprecated",
            "importance": 50,
        }
        with self.assertRaises(ApiServiceError) as error:
            parse_import_document("json", _json_document([fact] * 1001))
        self.assertEqual(error.exception.status_code, 413)

    def test_export_rejects_payload_that_cannot_be_reimported(self):
        repo = MagicMock()
        repo.list_all_facts.return_value = [_row()]
        with (
            self._patch_repo(repo),
            patch(
                "services.context_vault_portability.MAX_CONTEXT_VAULT_IMPORT_BYTES",
                10,
            ),
        ):
            with self.assertRaises(ApiServiceError) as error:
                build_export(7, "json")
        self.assertEqual(error.exception.status_code, 409)

    def test_preview_skips_file_and_existing_duplicates_and_reports_cap(self):
        new_fact = {
            "fact_type": "profile",
            "title": "Name",
            "content": "Kota",
            "status": "active",
            "importance": 50,
        }
        existing_fact = {
            "fact_type": "preference",
            "title": "Editor",
            "content": "Vim",
            "status": "active",
            "importance": 80,
        }
        repo = MagicMock()
        repo.find_existing_portable_signatures.return_value = {
            ("preference", "Editor", "Vim", "active", 80)
        }
        repo.count_active.return_value = 200
        with (
            self._patch_repo(repo),
            patch(
                "services.context_vault_portability.get_session_secret_key",
                return_value="test-secret",
            ),
        ):
            result = preview_import(
                7,
                "json",
                _json_document([new_fact, new_fact, existing_fact]),
            )

        self.assertEqual(result.total_count, 3)
        self.assertEqual(result.duplicate_count, 2)
        self.assertEqual(result.importable_count, 1)
        self.assertEqual(result.active_count, 1)
        self.assertEqual(result.deprecated_count, 0)
        self.assertFalse(result.can_import)
        self.assertTrue(result.preview_token)
        self.assertEqual(len(result.sample_facts), 1)
        self.assertEqual(result.duplicate_count + result.importable_count, result.total_count)

    def test_confirm_requires_exact_preview_and_schedules_only_active_embeddings(self):
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
        repo.find_existing_portable_signatures.return_value = set()
        repo.count_active.return_value = 0
        repo.bulk_import_facts.return_value = {
            "facts": [
                _row(id=11, fact_type="profile", title="Name", content="Kota", revision=1),
                _row(
                    id=12,
                    fact_type="reference",
                    title="Old",
                    content="Archived",
                    status="deprecated",
                    revision=1,
                ),
            ],
            "skipped_duplicate_count": 0,
            "active_count": 1,
            "deprecated_count": 1,
        }
        with (
            self._patch_repo(repo),
            patch(
                "services.context_vault_portability.get_session_secret_key",
                return_value="test-secret",
            ),
            patch("services.context_vault_portability.schedule_embedding") as schedule,
        ):
            preview = preview_import(7, "json", content)
            result = confirm_import(7, "json", content, preview.preview_token)

        self.assertEqual(result.imported_count, 2)
        self.assertEqual(result.active_count, 1)
        self.assertEqual(result.deprecated_count, 1)
        schedule.assert_called_once()
        self.assertEqual(schedule.call_args.args[0], 11)

        changed = _json_document([{**facts[0], "content": "Changed"}])
        with (
            self._patch_repo(repo),
            patch(
                "services.context_vault_portability.get_session_secret_key",
                return_value="test-secret",
            ),
        ):
            with self.assertRaises(ApiServiceError) as error:
                confirm_import(7, "json", changed, preview.preview_token)
        self.assertEqual(error.exception.status_code, 400)

    def test_confirm_rejects_tampered_token(self):
        content = _json_document(
            [
                {
                    "fact_type": "profile",
                    "title": "Name",
                    "content": "Kota",
                    "status": "active",
                    "importance": 50,
                }
            ]
        )
        with patch(
            "services.context_vault_portability.get_session_secret_key",
            return_value="test-secret",
        ):
            with self.assertRaises(ApiServiceError) as error:
                confirm_import(7, "json", content, "tampered")
        self.assertEqual(error.exception.status_code, 400)

    def test_preview_token_is_bound_to_owner(self):
        fact = {
            "fact_type": "profile",
            "title": "Name",
            "content": "Kota",
            "status": "active",
            "importance": 50,
        }
        content = _json_document([fact])
        repo = MagicMock()
        repo.find_existing_portable_signatures.return_value = set()
        repo.count_active.return_value = 0
        with (
            self._patch_repo(repo),
            patch(
                "services.context_vault_portability.get_session_secret_key",
                return_value="test-secret",
            ),
        ):
            preview = preview_import(7, "json", content)
            with self.assertRaises(ApiServiceError) as error:
                confirm_import(8, "json", content, preview.preview_token)
        self.assertEqual(error.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
