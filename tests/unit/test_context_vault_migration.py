import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


migration_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260719_01_add_context_facts.py"
)
spec = importlib.util.spec_from_file_location("context_vault_migration", migration_path)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the context vault migration module.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def _normalized_statements(execute):
    return [" ".join(call.args[0].split()) for call in execute.call_args_list]


class ContextVaultMigrationTestCase(unittest.TestCase):
    def test_revision_follows_mcp_reauthorization_migration(self):
        self.assertEqual(migration.revision, "20260719_01")
        self.assertEqual(migration.down_revision, "20260716_03")

    def test_upgrade_creates_context_facts_trigger_and_indexes(self):
        with (
            patch.object(migration.op, "execute") as execute,
            patch.object(migration.op, "get_context") as get_context,
        ):
            migration.upgrade()

        statements = _normalized_statements(execute)
        combined_sql = "\n".join(statements)
        get_context.return_value.autocommit_block.assert_called_once_with()

        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", statements)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS pg_trgm", statements)
        self.assertIn("CREATE TABLE IF NOT EXISTS context_facts", combined_sql)
        self.assertIn("revision BIGINT NOT NULL DEFAULT 1", combined_sql)
        self.assertIn("embedding_vector vector(768)", combined_sql)
        self.assertIn("trg_context_facts_updated_at", combined_sql)
        self.assertIn("EXECUTE FUNCTION set_updated_at()", combined_sql)

        for index_name in (
            "idx_context_facts_user_status_type",
            "idx_context_facts_user_updated_id",
            "idx_context_facts_content_trgm",
            "idx_context_facts_embedding_hnsw",
        ):
            self.assertIn(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name}",
                combined_sql,
            )
        self.assertIn("content gin_trgm_ops", combined_sql)
        self.assertIn("embedding_vector vector_cosine_ops", combined_sql)
        self.assertIn("WHERE embedding_vector IS NOT NULL", combined_sql)

    def test_upgrade_widens_client_metadata_without_grant_or_token_changes(self):
        with (
            patch.object(migration.op, "execute") as execute,
            patch.object(migration.op, "get_context"),
        ):
            migration.upgrade()

        statements = _normalized_statements(execute)
        scope_statements = [sql for sql in statements if "context:read" in sql]

        self.assertEqual(len(scope_statements), 1)
        self.assertIn("UPDATE mcp_oauth_clients", scope_statements[0])
        self.assertIn("metadata = jsonb_set", scope_statements[0])
        self.assertIn("context:read context:write", scope_statements[0])
        self.assertNotIn("mcp_oauth_grants", scope_statements[0])
        self.assertNotIn("mcp_oauth_tokens", scope_statements[0])
        self.assertFalse(any("UPDATE mcp_oauth_grants" in sql for sql in statements))
        self.assertFalse(any("UPDATE mcp_oauth_tokens" in sql for sql in statements))

    def test_downgrade_reverts_metadata_and_drops_vault_objects(self):
        with (
            patch.object(migration.op, "execute") as execute,
            patch.object(migration.op, "get_context") as get_context,
        ):
            migration.downgrade()

        statements = _normalized_statements(execute)
        combined_sql = "\n".join(statements)
        get_context.return_value.autocommit_block.assert_called_once_with()

        self.assertIn("UPDATE mcp_oauth_clients", statements[0])
        self.assertIn(
            "WHERE metadata ->> 'scope' = 'prompts:read prompts:write memos:read memos:write context:read context:write'",
            statements[0],
        )
        self.assertIn(
            "DROP INDEX CONCURRENTLY IF EXISTS idx_context_facts_embedding_hnsw",
            statements,
        )
        self.assertIn(
            "DROP TRIGGER IF EXISTS trg_context_facts_updated_at ON context_facts",
            statements,
        )
        self.assertIn("DROP TABLE IF EXISTS context_facts", statements)
        self.assertNotIn("DROP EXTENSION", combined_sql)


if __name__ == "__main__":
    unittest.main()
