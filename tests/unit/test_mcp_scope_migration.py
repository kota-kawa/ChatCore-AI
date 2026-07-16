import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


migration_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260716_03_reauthorize_legacy_mcp_connections.py"
)
spec = importlib.util.spec_from_file_location("mcp_scope_migration", migration_path)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the MCP scope migration module.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class McpScopeMigrationTestCase(unittest.TestCase):
    def test_upgrade_marks_legacy_grants_and_expands_client_registration(self):
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()

        statements = [" ".join(call.args[0].split()) for call in execute.call_args_list]
        self.assertEqual(len(statements), 3)
        self.assertIn("ADD COLUMN IF NOT EXISTS scope_version", statements[0])
        self.assertIn("UPDATE mcp_oauth_grants", statements[1])
        self.assertIn("scopes <> ARRAY['prompts:write']::text[]", statements[1])
        self.assertIn("UPDATE mcp_oauth_clients", statements[2])
        self.assertIn("prompts:read prompts:write memos:read memos:write", statements[2])

    def test_downgrade_removes_scope_version(self):
        with patch.object(migration.op, "execute") as execute:
            migration.downgrade()

        execute.assert_called_once_with(
            "ALTER TABLE mcp_oauth_grants DROP COLUMN IF EXISTS scope_version"
        )


if __name__ == "__main__":
    unittest.main()
