"""alembic マイグレーション 20261120_01（記憶の出典 context_fact_sources の作成）の連鎖と、作られる表・制約・索引、
およびモデルとの一致を検証するテスト。

Tests the revision chain of alembic migration 20261120_01, which creates context_fact_sources, the table,
constraints and indexes it creates, and agreement with the model.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from services.models import ContextFactSource

migration_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261120_01_add_context_fact_sources.py"
)
spec = importlib.util.spec_from_file_location("context_fact_sources_migration", migration_path)
if spec is None or spec.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("Unable to load the context fact sources migration.")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


# 日本語: op.create_table / create_index に渡された内容を集めます。
# English: Collect what the migration passed to op.create_table and op.create_index.
def _run_upgrade():
    with (
        patch.object(migration.op, "create_table") as create_table,
        patch.object(migration.op, "create_index") as create_index,
    ):
        migration.upgrade()
    return create_table, create_index


def _columns(create_table):
    return {item.name: item for item in create_table.call_args.args[1:] if hasattr(item, "nullable")}


class ContextFactSourcesMigrationTestCase(unittest.TestCase):
    def test_revision_follows_the_default_on_migration(self):
        self.assertEqual(migration.revision, "20261120_01")
        self.assertEqual(migration.down_revision, "20261119_01")

    def test_upgrade_creates_the_table_with_cascading_foreign_keys(self):
        create_table, _ = _run_upgrade()

        self.assertEqual(create_table.call_args.args[0], "context_fact_sources")
        columns = _columns(create_table)
        self.assertEqual(
            set(columns),
            {"id", "fact_id", "user_id", "chat_room_id", "user_message_id", "evidence", "observed_at"},
        )
        self.assertEqual(
            {name for name, column in columns.items() if column.nullable},
            {"user_message_id"},
        )
        self.assertEqual(columns["chat_room_id"].type.length, 255)
        foreign_keys = {
            tuple(constraint.column_keys): (str(constraint.elements[0].target_fullname), constraint.ondelete)
            for constraint in create_table.call_args.args[1:]
            if constraint.__class__.__name__ == "ForeignKeyConstraint"
        }
        self.assertEqual(
            foreign_keys,
            {
                ("fact_id",): ("context_facts.id", "CASCADE"),
                ("user_id",): ("users.id", "CASCADE"),
                ("chat_room_id",): ("chat_rooms.id", "CASCADE"),
                ("user_message_id",): ("chat_history.id", "SET NULL"),
            },
        )
        checks = [
            constraint
            for constraint in create_table.call_args.args[1:]
            if constraint.__class__.__name__ == "CheckConstraint"
        ]
        self.assertEqual(
            [(check.name, str(check.sqltext)) for check in checks],
            [("ck_context_fact_sources_evidence", "char_length(evidence) BETWEEN 1 AND 1000")],
        )

    def test_upgrade_creates_only_the_needed_indexes(self):
        _, create_index = _run_upgrade()

        created = {call.args[0]: call for call in create_index.call_args_list}
        self.assertEqual(
            set(created),
            {
                "idx_context_fact_sources_fact_observed",
                "idx_context_fact_sources_room",
                "idx_context_fact_sources_user",
                "uq_context_fact_sources_fact_message",
                "idx_context_fact_sources_message",
            },
        )
        unique = created["uq_context_fact_sources_fact_message"]
        self.assertTrue(unique.kwargs["unique"])
        self.assertEqual(unique.args[2], ["fact_id", "user_message_id"])
        self.assertEqual(str(unique.kwargs["postgresql_where"]), "user_message_id IS NOT NULL")
        for name, call in created.items():
            self.assertEqual(call.args[1], "context_fact_sources", name)

    def test_downgrade_drops_only_the_new_table(self):
        with patch.object(migration.op, "drop_table") as drop_table:
            migration.downgrade()

        drop_table.assert_called_once_with("context_fact_sources")

    def test_model_matches_the_migration(self):
        table = ContextFactSource.__table__
        create_sql = " ".join(str(CreateTable(table).compile(dialect=dialect())).split())
        self.assertIn("evidence TEXT NOT NULL", create_sql)
        self.assertIn("observed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL", create_sql)
        self.assertIn("FOREIGN KEY(user_message_id) REFERENCES chat_history (id) ON DELETE SET NULL", create_sql)
        self.assertIn("CONSTRAINT ck_context_fact_sources_evidence CHECK (char_length(evidence) BETWEEN 1 AND 1000)", create_sql)
        _, create_index = _run_upgrade()
        self.assertEqual(
            {index.name for index in table.indexes},
            {call.args[0] for call in create_index.call_args_list},
        )
        unique_sql = next(
            " ".join(str(CreateIndex(index).compile(dialect=dialect())).split())
            for index in table.indexes
            if index.name == "uq_context_fact_sources_fact_message"
        )
        self.assertEqual(
            unique_sql,
            "CREATE UNIQUE INDEX uq_context_fact_sources_fact_message ON context_fact_sources (fact_id, user_message_id) "
            "WHERE user_message_id IS NOT NULL",
        )


if __name__ == "__main__":
    unittest.main()
