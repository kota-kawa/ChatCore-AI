from __future__ import annotations

import unittest

from sqlalchemy.dialects.postgresql import JSONB, dialect as postgresql_dialect
from sqlalchemy.schema import CreateIndex
from sqlalchemy.types import Text

from services.models import (
    Base,
    ChatHistory,
    ContextFact,
    MemoEntry,
    Prompt,
    PromptVersion,
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


if __name__ == "__main__":
    unittest.main()
