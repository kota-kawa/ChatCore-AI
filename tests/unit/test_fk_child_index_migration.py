"""Keep 20260913_02's indexes and foreign keys in step with the models.

The revision adds the indexes a parent delete needs on each foreign-key child
column, plus the ``client_id`` foreign keys 20260713_01 left out of the MCP
OAuth tables.  Autogenerate compares ``Base.metadata`` against the migrated
schema, so a name that exists in only one of the two would show up as a
spurious create/drop on the next revision.
"""

import unittest
from pathlib import Path

from services.models import (
    Base,
    GuestPromptSubmission,
    McpOAuthAuthorizationCode,
    McpOAuthGrant,
    McpOAuthToken,
    McpOAuthUserClient,
    MemoryFact,
    Task,
    UserSkill,
)

MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260913_02_add_missing_child_indexes_and_client_fks.py"
)

EXPECTED_INDEXES = {
    "idx_memory_facts_room_scope_fact": MemoryFact,
    "idx_memory_facts_source_message_id": MemoryFact,
    "idx_guest_prompt_submissions_claimed_by_user": GuestPromptSubmission,
    "idx_user_skills_source_prompt_id": UserSkill,
    "idx_task_with_examples_source_prompt_id": Task,
    "idx_mcp_oauth_codes_grant_id": McpOAuthAuthorizationCode,
    "idx_mcp_oauth_grants_client_id": McpOAuthGrant,
    "idx_mcp_oauth_codes_client_id": McpOAuthAuthorizationCode,
    "idx_mcp_oauth_tokens_client_id": McpOAuthToken,
}

EXPECTED_CLIENT_FOREIGN_KEYS = {
    "fk_mcp_oauth_grants_client_id": McpOAuthGrant,
    "fk_mcp_oauth_authorization_codes_client_id": McpOAuthAuthorizationCode,
    "fk_mcp_oauth_tokens_client_id": McpOAuthToken,
}


def _upgrade_source() -> str:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    return source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]


class FkChildIndexMigrationTestCase(unittest.TestCase):
    def test_revision_chains_onto_the_previous_head(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn('revision: str = "20260913_02"', source)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "20260913_01"', source)

    def test_upgrade_is_additive(self):
        upgrade = _upgrade_source()
        # expand/contract: 索引と NOT VALID の外部キーを足すだけで、既存の行や制約には触れない。
        # Expand/contract: indexes and NOT VALID foreign keys only; no existing row or constraint moves.
        self.assertNotIn("DROP", upgrade.upper())
        self.assertNotIn("op.drop_", upgrade)
        self.assertNotIn("op.alter_column", upgrade)
        # 孤児行が居ても ALTER が失敗しないよう、外部キーは NOT VALID で追加する。
        # The foreign keys are added NOT VALID so pre-existing orphans cannot fail the ALTER.
        self.assertEqual(upgrade.count("postgresql_not_valid=True"), 1)
        self.assertIn('ondelete="CASCADE"', upgrade)

    def test_every_new_index_exists_in_both_the_migration_and_the_model(self):
        upgrade = _upgrade_source()
        for index_name, model in EXPECTED_INDEXES.items():
            with self.subTest(index=index_name):
                self.assertIn(index_name, upgrade)
                self.assertIn(index_name, {index.name for index in model.__table__.indexes})

    def test_memory_fact_lookup_index_matches_the_duplicate_check(self):
        index = next(
            index
            for index in MemoryFact.__table__.indexes
            if index.name == "idx_memory_facts_room_scope_fact"
        )
        rendered = [str(expression) for expression in index.expressions]
        self.assertEqual(
            rendered,
            ["memory_facts.chat_room_id", "memory_facts.scope", "lower(fact)"],
        )
        self.assertIn('sa.text("lower(fact)")', _upgrade_source())
        # is_active を条件に持たないため、既存の部分索引では代用できない。
        # The existing partial indexes are filtered on is_active, which this lookup never constrains.
        self.assertIsNone(index.dialect_options["postgresql"]["where"])

    def test_client_id_foreign_keys_exist_in_both_places(self):
        upgrade = _upgrade_source()
        for constraint_name, model in EXPECTED_CLIENT_FOREIGN_KEYS.items():
            with self.subTest(constraint=constraint_name):
                self.assertIn(constraint_name, upgrade)
                constraint = next(
                    (
                        candidate
                        for candidate in model.__table__.foreign_key_constraints
                        if candidate.name == constraint_name
                    ),
                    None,
                )
                self.assertIsNotNone(constraint)
                assert constraint is not None
                self.assertEqual([column.name for column in constraint.columns], ["client_id"])
                self.assertEqual(
                    [element.target_fullname for element in constraint.elements],
                    ["mcp_oauth_clients.client_id"],
                )
                self.assertEqual(constraint.ondelete, "CASCADE")

    def test_set_null_children_are_indexed_without_a_leading_user_id(self):
        # 既存の複合索引は先頭が user_id のため、prompts 1行の削除には使えない。
        # The existing composite indexes lead with user_id, so a single prompt delete cannot use them.
        for model, index_name in (
            (UserSkill, "idx_user_skills_source_prompt_id"),
            (Task, "idx_task_with_examples_source_prompt_id"),
            (MemoryFact, "idx_memory_facts_source_message_id"),
            (GuestPromptSubmission, "idx_guest_prompt_submissions_claimed_by_user"),
        ):
            with self.subTest(index=index_name):
                index = next(i for i in model.__table__.indexes if i.name == index_name)
                self.assertEqual(len(index.expressions), 1)
                self.assertIsNotNone(index.dialect_options["postgresql"]["where"])

    def test_user_client_provider_index_stays_dropped(self):
        # 20260713_02 が作った部分ユニーク索引は 20260714_01 が意図的に削除した
        # （1ユーザーが provider ごとに複数の認証情報を持てるようにするため）。モデルへ
        # 宣言し直すと、その仕様を巻き戻す一意制約を復活させてしまう。
        # 20260713_02 created this partial unique index and 20260714_01 deliberately removed it so a
        # user can hold several credentials per provider. Re-declaring it on the model would bring
        # back the uniqueness that change removed.
        self.assertNotIn(
            "uq_mcp_oauth_user_clients_active_provider",
            {index.name for index in McpOAuthUserClient.__table__.indexes},
        )

    def test_no_new_table_was_introduced(self):
        self.assertNotIn("create_table", _upgrade_source())
        self.assertIn("memory_facts", Base.metadata.tables)


if __name__ == "__main__":
    unittest.main()
