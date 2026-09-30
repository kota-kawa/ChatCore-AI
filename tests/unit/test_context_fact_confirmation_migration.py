import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

migration_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260930_01_add_context_fact_confirmation.py"
)
spec = importlib.util.spec_from_file_location("context_fact_confirmation_migration", migration_path)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the context fact confirmation migration module.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def _statements(execute):
    return [" ".join(call.args[0].split()) for call in execute.call_args_list]


class ContextFactConfirmationMigrationTestCase(unittest.TestCase):
    def test_revision_follows_prompt_tools_skill_migration(self):
        self.assertEqual(migration.revision, "20260930_01")
        self.assertEqual(migration.down_revision, "20260928_01")

    def test_upgrade_adds_nullable_columns_with_range_check(self):
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()

        alter = _statements(execute)[0]
        self.assertIn("ADD COLUMN confidence DOUBLE PRECISION,", alter)
        self.assertIn("ADD COLUMN last_confirmed_at TIMESTAMP,", alter)
        self.assertNotIn("NOT NULL", alter)
        self.assertIn("CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)", alter)

    def test_backfill_does_not_advance_updated_at(self):
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()

        statements = _statements(execute)
        disable = "ALTER TABLE context_facts DISABLE TRIGGER trg_context_facts_updated_at"
        enable = "ALTER TABLE context_facts ENABLE TRIGGER trg_context_facts_updated_at"
        self.assertIn(disable, statements)
        self.assertIn(enable, statements)
        updates = [index for index, sql in enumerate(statements) if sql.startswith("UPDATE context_facts")]
        self.assertTrue(updates)
        self.assertLess(statements.index(disable), min(updates))
        self.assertGreater(statements.index(enable), max(updates))
        self.assertFalse(any("updated_at =" in sql.replace("candidate.updated_at", "") for sql in statements))

    def test_backfill_confirms_chat_and_manual_but_not_mcp_or_import(self):
        with patch.object(migration.op, "execute") as execute:
            migration.upgrade()

        updates = [sql for sql in _statements(execute) if sql.startswith("UPDATE context_facts")]
        chat_from_candidate, chat_fallback, manual = updates
        self.assertIn("SET confidence = candidate.confidence, last_confirmed_at = candidate.updated_at", chat_from_candidate)
        self.assertIn("candidate.promoted_fact_id = fact.id", chat_from_candidate)
        self.assertIn("candidate.status = 'approved'", chat_from_candidate)
        self.assertIn("fact.source_kind = 'chat'", chat_from_candidate)
        self.assertIn("SET last_confirmed_at = created_at WHERE source_kind = 'chat' AND last_confirmed_at IS NULL", chat_fallback)
        self.assertIn("SET last_confirmed_at = created_at WHERE source_kind = 'manual'", manual)
        combined = "\n".join(updates)
        self.assertNotIn("'mcp'", combined)
        self.assertNotIn("'import'", combined)

    def test_downgrade_drops_columns_and_constraint(self):
        with patch.object(migration.op, "execute") as execute:
            migration.downgrade()

        statement = _statements(execute)[0]
        self.assertIn("DROP CONSTRAINT IF EXISTS ck_context_facts_confidence", statement)
        self.assertIn("DROP COLUMN IF EXISTS last_confirmed_at", statement)
        self.assertIn("DROP COLUMN IF EXISTS confidence", statement)


if __name__ == "__main__":
    unittest.main()
