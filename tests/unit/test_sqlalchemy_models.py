from __future__ import annotations

import unittest

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.schema import CreateIndex
from sqlalchemy.types import Text

from services.models import (
    Base,
    ChatHistory,
    ChatRoom,
    ContextFact,
    McpOAuthGrant,
    MemoEntry,
    Prompt,
    PromptVersion,
    SharedChatRoom,
    TaskVersion,
    User,
    UserAuthProvider,
    UserSkill,
)
from services.models.types import Vector


class SqlAlchemyModelMetadataTests(unittest.TestCase):
    def test_metadata_matches_current_table_inventory(self) -> None:
        expected_tables = {
            "users",
            "user_passkeys",
            "chat_rooms",
            "chat_history",
            "shared_chat_rooms",
            "chat_room_summaries",
            "memory_facts",
            "user_skills",
            "task_with_examples",
            "task_versions",
            "prompts",
            "prompt_versions",
            "user_auth_providers",
            "prompt_likes",
            "prompt_comments",
            "prompt_comment_reports",
            "memo_entries",
            "memo_collections",
            "shared_memo_entries",
            "projects",
            "project_files",
            "context_facts",
            "context_fact_candidates",
            "prompt_resources",
            "guest_prompt_submissions",
            "prompt_view_counts",
            "mcp_oauth_clients",
            "mcp_oauth_grants",
            "mcp_oauth_user_clients",
            "mcp_oauth_authorization_codes",
            "mcp_oauth_tokens",
        }
        self.assertEqual(set(Base.metadata.tables), expected_tables)
        self.assertNotIn("prompt_list_entries", Base.metadata.tables)
        self.assertNotIn("input_content", MemoEntry.__table__.columns)
        self.assertNotIn("auth_provider", User.__table__.columns)
        self.assertNotIn("provider_user_id", User.__table__.columns)
        self.assertTrue(MemoEntry.created_at.nullable)
        self.assertTrue(Prompt.updated_at.nullable)
        self.assertFalse(UserAuthProvider.created_at.nullable)
        self.assertTrue(PromptVersion.user_id.nullable)
        self.assertFalse(PromptVersion.snapshot.nullable)
        self.assertFalse(TaskVersion.snapshot.nullable)
        self.assertFalse(MemoEntry.embedding_status.nullable)
        self.assertFalse(ContextFact.embedding_status.nullable)
        self.assertFalse(UserSkill.is_enabled.nullable)
        self.assertTrue(UserSkill.source_prompt_id.nullable)
        self.assertFalse(User.generative_ui_skill_enabled.nullable)
        self.assertFalse(ChatRoom.last_activity_at.nullable)
        # 共有チャットの失効・期限は expand のみで追加したため NULL 許容のまま。
        # Chat share lifecycle columns were added expand-only, so both stay nullable.
        self.assertTrue(SharedChatRoom.expires_at.nullable)
        self.assertTrue(SharedChatRoom.revoked_at.nullable)
        self.assertTrue(SharedChatRoom.expires_at.type.timezone)
        self.assertTrue(SharedChatRoom.revoked_at.type.timezone)

    def test_postgresql_specific_types_and_indexes_compile(self) -> None:
        self.assertIsInstance(User.username.type, Text)
        self.assertIsInstance(User.avatar_url.type, Text)
        self.assertIsInstance(ChatHistory.message_parts.type, JSONB)
        self.assertIsInstance(Prompt.attributes.type, JSONB)
        self.assertIsInstance(MemoEntry.embedding_vector.type, Vector)
        self.assertEqual(MemoEntry.embedding_vector.type.compile(dialect=postgresql_dialect()), "vector(768)")

        index_sql = {
            str(CreateIndex(index).compile(dialect=postgresql_dialect()))
            for table in Base.metadata.tables.values()
            for index in table.indexes
        }
        self.assertTrue(any("USING hnsw" in statement for statement in index_sql))
        self.assertTrue(any("WHERE" in statement for statement in index_sql))
        self.assertTrue(any("idx_user_skills_user_source_prompt" in statement for statement in index_sql))
        self.assertTrue(any("idx_chat_rooms_user_last_activity_id" in statement for statement in index_sql))
        # FK 子カラム側の索引。親1行の削除が子表を全走査しないために要る。
        # Indexes on the FK child columns, so deleting one parent row does not scan the child table.
        for index_name in (
            "idx_memory_facts_room_scope_fact",
            "idx_memory_facts_source_message_id",
            "idx_guest_prompt_submissions_claimed_by_user",
            "idx_user_skills_source_prompt_id",
            "idx_task_with_examples_source_prompt_id",
            "idx_mcp_oauth_codes_grant_id",
            "idx_mcp_oauth_grants_client_id",
            "idx_mcp_oauth_codes_client_id",
            "idx_mcp_oauth_tokens_client_id",
        ):
            with self.subTest(index=index_name):
                self.assertTrue(any(index_name in statement for statement in index_sql))

    def test_mcp_oauth_client_id_columns_reference_the_client_table(self):
        # 20260713_01 は user_id / grant_id にだけ REFERENCES を付け、client_id を素の TEXT の
        # まま残していた。クライアント削除でグラント・トークンが孤児化する。
        # 20260713_01 gave user_id and grant_id a REFERENCES clause and left client_id bare TEXT,
        # which orphans grants and tokens when a client row is deleted.
        constraint = next(
            candidate
            for candidate in McpOAuthGrant.__table__.foreign_key_constraints
            if candidate.name == "fk_mcp_oauth_grants_client_id"
        )
        self.assertEqual([column.name for column in constraint.columns], ["client_id"])
        self.assertEqual(
            [element.target_fullname for element in constraint.elements],
            ["mcp_oauth_clients.client_id"],
        )
        self.assertEqual(constraint.ondelete, "CASCADE")


if __name__ == "__main__":
    unittest.main()
