"""SQLAlchemy 2.0 mappings for the current ChatCore PostgreSQL schema.

The migration history remains the source of truth for schema evolution.  These
models describe the schema at the current Alembic head and are intentionally
kept separate from Pydantic request/response contracts.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    desc,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CHAR, DOUBLE_PRECISION, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .types import Vector


def _timestamp(*, timezone: bool = False, nullable: bool = True) -> Mapped[datetime | None]:
    return mapped_column(
        DateTime(timezone=timezone),
        nullable=nullable,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ユーザー'"))
    bio: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'/static/user-icon.png'"))
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=True, server_default=text("FALSE"))
    created_at: Mapped[datetime | None] = _timestamp()
    llm_profile_context: Mapped[str | None] = mapped_column(Text)
    context_auto_extract_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    preferred_locale: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (
        Index("idx_users_username_trgm", "username", postgresql_using="gin",
              postgresql_ops={"username": "gin_trgm_ops"}),
    )


class UserPasskey(Base):
    __tablename__ = "user_passkeys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credential_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    aaguid: Mapped[str | None] = mapped_column(String(64))
    credential_device_type: Mapped[str | None] = mapped_column(String(32))
    credential_backed_up: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    label: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime | None] = _timestamp()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (Index("idx_user_passkeys_user_created_at", "user_id", desc("created_at")),)


class ChatRoom(Base):
    __tablename__ = "chat_rooms"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), server_default=text("'新規チャット'"))
    created_at: Mapped[datetime | None] = _timestamp()
    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'normal'"))
    active_root_id: Mapped[int | None] = mapped_column(Integer)
    project_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("projects.id", ondelete="SET NULL"))

    __table_args__ = (
        CheckConstraint("mode IN ('normal', 'temporary')", name="chk_chat_rooms_mode"),
        Index("idx_chat_rooms_user_created_at", "user_id", desc("created_at")),
        Index("idx_chat_rooms_user_created_at_id", "user_id", desc("created_at"), desc("id")),
        Index("idx_chat_rooms_project_created_at", "project_id", desc("created_at")),
    )


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_room_id: Mapped[str] = mapped_column(String(255), ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    sender: Mapped[str | None] = mapped_column(String(20))
    timestamp: Mapped[datetime | None] = _timestamp()
    attached_file_names: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chat_history.id", ondelete="CASCADE"))
    active_child_id: Mapped[int | None] = mapped_column(Integer)
    message_parts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    attached_file_contents: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    web_search_context: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint("sender IN ('user', 'assistant')", name="chat_history_sender_check"),
        Index("idx_chat_history_room_id_id", "chat_room_id", "id"),
        Index("idx_chat_history_room_parent", "chat_room_id", "parent_id"),
    )


class SharedChatRoom(Base):
    __tablename__ = "shared_chat_rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_room_id: Mapped[str] = mapped_column(String(255), ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False, unique=True)
    share_token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime | None] = _timestamp()

    __table_args__ = (Index("idx_shared_chat_rooms_token_created_at", "share_token", desc("created_at")),)


class ChatRoomSummary(Base):
    __tablename__ = "chat_room_summaries"

    chat_room_id: Mapped[str] = mapped_column(String(255), ForeignKey("chat_rooms.id", ondelete="CASCADE"), primary_key=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    archived_message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class MemoryFact(Base):
    __tablename__ = "memory_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    chat_room_id: Mapped[str | None] = mapped_column(String(255), ForeignKey("chat_rooms.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'room'"))
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chat_history.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        CheckConstraint("scope IN ('room', 'user')", name="chk_memory_facts_scope"),
        Index("idx_memory_facts_room_updated_at", "chat_room_id", desc("updated_at"), postgresql_where=text("is_active = TRUE")),
        Index("idx_memory_facts_user_updated_at", "user_id", desc("updated_at"), postgresql_where=text("is_active = TRUE")),
    )


class UserSkill(Base):
    __tablename__ = "user_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_prompt_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("prompts.id", ondelete="SET NULL"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at: Mapped[datetime | None] = _timestamp()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 100", name="chk_user_skills_name_length"),
        CheckConstraint("char_length(btrim(instructions)) BETWEEN 1 AND 12000", name="chk_user_skills_instructions_length"),
        Index("idx_user_skills_user_created_at", "user_id", "created_at", "id"),
        Index("idx_user_skills_user_enabled", "user_id", "is_enabled", "id"),
        Index("idx_user_skills_user_source_prompt", "user_id", "source_prompt_id"),
        Index(
            "uq_user_skills_user_normalized_name",
            "user_id",
            text("lower(btrim(name))"),
            unique=True,
        ),
    )


class Task(Base):
    __tablename__ = "task_with_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    response_rules: Mapped[str | None] = mapped_column(Text)
    output_skeleton: Mapped[str | None] = mapped_column(Text)
    input_examples: Mapped[str | None] = mapped_column(Text)
    output_examples: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime | None] = _timestamp()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_prompt_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("prompts.id", ondelete="SET NULL"))
    system_task_key: Mapped[str | None] = mapped_column(String(64))
    system_task_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_system_task_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))

    __table_args__ = (
        Index("idx_task_with_examples_user_name", "user_id", "name"),
        Index("idx_task_with_examples_user_order", "user_id", "display_order", "id"),
        Index("idx_task_with_examples_user_created_at", "user_id", desc("created_at"), desc("id")),
        Index("idx_task_with_examples_system_task_key", "system_task_key"),
        Index("idx_task_with_examples_active_user_order", "user_id", "display_order", "id", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_task_with_examples_active_user_name", "user_id", "name", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_task_with_examples_active_user_source_prompt", "user_id", "source_prompt_id", postgresql_where=text("deleted_at IS NULL")),
        Index("uq_task_with_examples_active_shared_normalized_name", text("lower(btrim(name))"), unique=True,
              postgresql_where=text("user_id IS NULL AND deleted_at IS NULL")),
        Index("uq_task_with_examples_active_user_normalized_name", "user_id", text("lower(btrim(name))"), unique=True,
              postgresql_where=text("user_id IS NOT NULL AND deleted_at IS NULL")),
        Index("uq_task_with_examples_active_shared_system_key", "system_task_key", unique=True,
              postgresql_where=text("user_id IS NULL AND system_task_key IS NOT NULL AND deleted_at IS NULL")),
        Index("uq_task_with_examples_active_user_system_key", "user_id", "system_task_key", unique=True,
              postgresql_where=text("user_id IS NOT NULL AND system_task_key IS NOT NULL AND deleted_at IS NULL")),
        Index("uq_task_with_examples_active_user_source_prompt", "user_id", "source_prompt_id", unique=True,
              postgresql_where=text("user_id IS NOT NULL AND source_prompt_id IS NOT NULL AND deleted_at IS NULL")),
    )


class TaskVersion(Base):
    __tablename__ = "task_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("task_with_examples.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    response_rules: Mapped[str | None] = mapped_column(Text)
    output_skeleton: Mapped[str | None] = mapped_column(Text)
    input_examples: Mapped[str | None] = mapped_column(Text)
    output_examples: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int | None] = mapped_column(Integer)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("task_id", "version_number", name="uq_task_versions_task_version"),
        Index("idx_task_versions_task_created_at", "task_id", desc("created_at")),
    )


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(50), nullable=False)
    input_examples: Mapped[str | None] = mapped_column(Text)
    output_examples: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    ai_model: Mapped[str | None] = mapped_column(String(100), server_default=text("NULL::character varying"))
    content_format: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'prompt'"))
    media_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'text'"))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    attachments: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    legacy_category: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("''"))
    system_prompt_key: Mapped[str | None] = mapped_column(String(64))
    content_locale: Mapped[str | None] = mapped_column(String(16))
    description: Mapped[str | None] = mapped_column(String(300), server_default=text("NULL::character varying"))

    __table_args__ = (
        Index("idx_prompts_public_created_at", "is_public", desc("created_at")),
        Index("idx_prompts_user_created_at", "user_id", desc("created_at")),
        Index("idx_prompts_active_public_created_at", "is_public", desc("created_at"), postgresql_where=text("deleted_at IS NULL")),
        Index("idx_prompts_active_user_created_at", "user_id", desc("created_at"), postgresql_where=text("deleted_at IS NULL")),
        Index("idx_prompts_active_public_created_at_id", desc("created_at"), desc("id"), postgresql_where=text("is_public = TRUE AND deleted_at IS NULL")),
        Index("idx_prompts_public_category", "category", postgresql_where=text("is_public = TRUE")),
        Index("idx_prompts_public_author_trgm", "author", postgresql_using="gin", postgresql_ops={"author": "gin_trgm_ops"}, postgresql_where=text("is_public = TRUE")),
        Index("idx_prompts_system_prompt_locale", "system_prompt_key", "content_locale"),
        Index("idx_prompts_public_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}, postgresql_where=text("is_public = TRUE")),
        Index("idx_prompts_public_content_trgm", "content", postgresql_using="gin", postgresql_ops={"content": "gin_trgm_ops"}, postgresql_where=text("is_public = TRUE")),
        Index("idx_prompts_public_description_trgm", "description", postgresql_using="gin", postgresql_ops={"description": "gin_trgm_ops"}, postgresql_where=text("is_public = TRUE AND description IS NOT NULL")),
        Index("idx_prompts_public_skill_markdown_trgm", text("(COALESCE(attributes ->> 'skill_markdown', ''))"), postgresql_using="gin", postgresql_ops={"(COALESCE(attributes ->> 'skill_markdown', ''))": "gin_trgm_ops"}, postgresql_where=text("is_public = TRUE AND deleted_at IS NULL AND content_format = 'skill'")),
    )


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(50), nullable=False)
    input_examples: Mapped[str | None] = mapped_column(Text)
    output_examples: Mapped[str | None] = mapped_column(Text)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("prompt_id", "version_number", name="uq_prompt_versions_prompt_version"),
        Index("idx_prompt_versions_prompt_created_at", "prompt_id", desc("created_at")),
    )


class UserAuthProvider(Base):
    __tablename__ = "user_auth_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_user_id: Mapped[str | None] = mapped_column(String(255))
    provider_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_auth_providers_user_provider"),
        Index("uq_user_auth_providers_provider_identity", "provider", "provider_user_id", unique=True,
              postgresql_where=text("provider_user_id IS NOT NULL")),
        Index("idx_user_auth_providers_user_provider", "user_id", "provider"),
    )


class PromptLike(Base):
    __tablename__ = "prompt_likes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    prompt_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime | None] = _timestamp()

    __table_args__ = (
        UniqueConstraint("user_id", "prompt_id", name="uq_prompt_likes_user_prompt"),
        Index("idx_prompt_likes_user_created_at", "user_id", desc("created_at"), desc("id")),
        Index("idx_prompt_likes_prompt_created_at", "prompt_id", desc("created_at"), desc("id")),
    )


class PromptComment(Base):
    __tablename__ = "prompt_comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prompt_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    hidden_by_reports_at: Mapped[datetime | None] = mapped_column(DateTime)
    hidden_reason: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("idx_prompt_comments_prompt_visible_created_at", "prompt_id", desc("created_at"), desc("id"),
              postgresql_where=text("deleted_at IS NULL AND hidden_by_reports_at IS NULL")),
        Index("idx_prompt_comments_user_created_at", "user_id", desc("created_at"), desc("id")),
    )


class PromptCommentReport(Base):
    __tablename__ = "prompt_comment_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    comment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prompt_comments.id", ondelete="CASCADE"), nullable=False)
    reporter_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("comment_id", "reporter_user_id", name="uq_prompt_comment_reports_comment_reporter"),
        Index("idx_prompt_comment_reports_comment_created_at", "comment_id", desc("created_at"), desc("id")),
        Index("idx_prompt_comment_reports_reporter_created_at", "reporter_user_id", desc("created_at"), desc("id")),
    )


class MemoEntry(Base):
    __tablename__ = "memo_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    ai_response: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime)
    collection_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("memo_collections.id", ondelete="SET NULL"))
    embedding: Mapped[str | None] = mapped_column(Text)
    embedding_vector: Mapped[list[float] | None] = mapped_column(Vector(768))
    embedding_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'pending'"),
    )
    sort_order: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    background_color: Mapped[str | None] = mapped_column(String(20))
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))

    __table_args__ = (
        CheckConstraint(
            "embedding_status IN ('pending', 'ready')",
            name="ck_memo_entries_embedding_status",
        ),
        Index("idx_memo_entries_created_at", desc("created_at")),
        Index("idx_memo_entries_user_created_at", "user_id", desc("created_at")),
        Index("idx_memo_entries_collection_id", "user_id", "collection_id", postgresql_where=text("collection_id IS NOT NULL")),
        Index("idx_memo_entries_has_embedding", "user_id", desc("created_at"), postgresql_where=text("embedding IS NOT NULL")),
        Index("idx_memo_entries_user_archived_pinned_created", "user_id", "archived_at", desc("pinned_at"), desc("created_at")),
        Index("idx_memo_entries_user_archived_pinned_sort", "user_id", "archived_at", "pinned_at", desc("sort_order")),
        Index("idx_memo_entries_user_updated_id", "user_id", desc("updated_at"), desc("id")),
        Index("idx_memo_entries_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
        Index("idx_memo_entries_response_trgm", "ai_response", postgresql_using="gin", postgresql_ops={"ai_response": "gin_trgm_ops"}),
        Index("idx_memo_entries_embedding_vector_hnsw", "embedding_vector", postgresql_using="hnsw", postgresql_ops={"embedding_vector": "vector_cosine_ops"}, postgresql_where=text("embedding_vector IS NOT NULL")),
    )


class MemoCollection(Base):
    __tablename__ = "memo_collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'#6b7280'"))
    created_at: Mapped[datetime | None] = _timestamp()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="memo_collections_user_id_name_key"),
        Index("idx_memo_collections_user_created", "user_id", desc("created_at")),
    )


class SharedMemoEntry(Base):
    __tablename__ = "shared_memo_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    memo_entry_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("memo_entries.id", ondelete="CASCADE"), nullable=False, unique=True)
    share_token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_shared_memo_entries_token_created_at", "share_token", desc("created_at")),
        Index("idx_shared_memo_entries_active_lookup", "memo_entry_id", "revoked_at", "expires_at"),
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("'新規プロジェクト'"))
    instructions: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = _timestamp()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (Index("idx_projects_user_created_at", "user_id", desc("created_at")),)


class ProjectFile(Base):
    __tablename__ = "project_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime | None] = _timestamp()

    __table_args__ = (Index("idx_project_files_project_id", "project_id", "id"),)


class ContextFact(Base):
    __tablename__ = "context_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    embedding_vector: Mapped[list[float] | None] = mapped_column(Vector(768))
    embedding_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'pending'"),
    )
    created_at: Mapped[datetime | None] = _timestamp()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'manual'"))
    source_ref: Mapped[str | None] = mapped_column(String(500))
    source_client_id: Mapped[str | None] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("50"))
    idempotency_key_hash: Mapped[str | None] = mapped_column(CHAR(64))
    idempotency_payload_hash: Mapped[str | None] = mapped_column(CHAR(64))

    __table_args__ = (
        CheckConstraint(
            "embedding_status IN ('pending', 'ready')",
            name="ck_context_facts_embedding_status",
        ),
        CheckConstraint("fact_type IN ('preference', 'profile', 'project', 'decision', 'reference')", name="chk_context_facts_fact_type"),
        CheckConstraint("char_length(title) >= 1", name="chk_context_facts_title"),
        CheckConstraint("char_length(content) BETWEEN 1 AND 2000", name="chk_context_facts_content"),
        CheckConstraint("status IN ('active', 'deprecated')", name="chk_context_facts_status"),
        CheckConstraint("source_kind IN ('manual', 'mcp', 'chat', 'import')", name="ck_context_facts_source_kind"),
        CheckConstraint("importance BETWEEN 0 AND 100", name="ck_context_facts_importance"),
        CheckConstraint("idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$'", name="ck_context_facts_idempotency_key_hash"),
        CheckConstraint("idempotency_payload_hash IS NULL OR idempotency_payload_hash ~ '^[0-9a-f]{64}$'", name="ck_context_facts_idempotency_payload_hash"),
        CheckConstraint("(idempotency_key_hash IS NULL) = (idempotency_payload_hash IS NULL)", name="ck_context_facts_idempotency_hash_pair"),
        UniqueConstraint("idempotency_key_hash", name="uq_context_facts_idempotency_key_hash"),
        Index("idx_context_facts_user_status_type", "user_id", "status", "fact_type", desc("updated_at")),
        Index("idx_context_facts_user_updated_id", "user_id", desc("updated_at"), desc("id")),
        Index("idx_context_facts_user_digest", "user_id", "status", desc("importance"), desc("updated_at"), desc("id")),
        Index("idx_context_facts_content_trgm", "content", postgresql_using="gin", postgresql_ops={"content": "gin_trgm_ops"}),
        Index("idx_context_facts_embedding_hnsw", "embedding_vector", postgresql_using="hnsw", postgresql_ops={"embedding_vector": "vector_cosine_ops"}, postgresql_where=text("embedding_vector IS NOT NULL")),
    )


class ContextFactCandidate(Base):
    __tablename__ = "context_fact_candidates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'chat'"))
    source_ref: Mapped[str | None] = mapped_column(String(500))
    source_client_id: Mapped[str | None] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("50"))
    confidence: Mapped[float] = mapped_column(DOUBLE_PRECISION, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    promoted_fact_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("context_facts.id", ondelete="SET NULL"))
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        CheckConstraint("fact_type IN ('preference', 'profile', 'project', 'decision', 'reference')", name="chk_context_fact_candidates_fact_type"),
        CheckConstraint("char_length(title) >= 1", name="chk_context_fact_candidates_title"),
        CheckConstraint("char_length(content) BETWEEN 1 AND 2000", name="chk_context_fact_candidates_content"),
        CheckConstraint("source_kind IN ('manual', 'mcp', 'chat', 'import')", name="chk_context_fact_candidates_source_kind"),
        CheckConstraint("importance BETWEEN 0 AND 100", name="chk_context_fact_candidates_importance"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="chk_context_fact_candidates_confidence"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="chk_context_fact_candidates_status"),
        CheckConstraint("fingerprint ~ '^[0-9a-f]{64}$'", name="chk_context_fact_candidates_fingerprint"),
        CheckConstraint("revision >= 1", name="chk_context_fact_candidates_revision"),
        Index("idx_context_fact_candidates_user_status", "user_id", "status", desc("created_at"), desc("id")),
        Index("uq_context_fact_candidates_pending_fingerprint", "user_id", "fingerprint", unique=True, postgresql_where=text("status = 'pending'")),
        Index("idx_context_fact_candidates_promoted_fact", "promoted_fact_id", postgresql_where=text("promoted_fact_id IS NOT NULL")),
    )


class PromptResource(Base):
    __tablename__ = "prompt_resources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prompt_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'text'"))
    media_type: Mapped[str] = mapped_column(String(128), nullable=False, server_default=text("'text/plain'"))
    text_content: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    sha256: Mapped[str | None] = mapped_column(CHAR(64))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("prompt_id", "path", name="uq_prompt_resources_prompt_path"),
        CheckConstraint("role IN ('script', 'reference', 'config', 'other')", name="ck_prompt_resources_role"),
        CheckConstraint("(text_content IS NOT NULL) <> (storage_key IS NOT NULL)", name="ck_prompt_resources_content_location"),
        CheckConstraint("size_bytes >= 0", name="ck_prompt_resources_size"),
        CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'", name="ck_prompt_resources_sha256"),
        Index("uq_prompt_resources_prompt_lower_path", "prompt_id", text("lower(path)"), unique=True),
        Index("idx_prompt_resources_prompt_order", "prompt_id", "sort_order", "id"),
    )


class GuestPromptSubmission(Base):
    __tablename__ = "guest_prompt_submissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prompt_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, unique=True)
    guest_cookie_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    client_ip_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    claimed_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("claimed_at IS NULL OR claimed_by_user_id IS NOT NULL", name="ck_guest_prompt_submissions_claimed_at"),
        Index("idx_guest_prompt_submissions_cookie_created_at", "guest_cookie_hash", desc("created_at")),
        Index("idx_guest_prompt_submissions_ip_created_at", "client_ip_hash", desc("created_at")),
    )


class PromptViewCount(Base):
    __tablename__ = "prompt_view_counts"

    prompt_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), primary_key=True)
    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint("view_count >= 0", name="ck_prompt_view_counts_non_negative"),
        Index("idx_prompt_view_counts_popular", desc("view_count"), desc("prompt_id")),
    )


class McpOAuthClient(Base):
    __tablename__ = "mcp_oauth_clients"

    client_id: Mapped[str] = mapped_column(Text, primary_key=True)
    client_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
    client_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    registration_method: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("registration_method IN ('dcr', 'cimd', 'pre_registered')", name="mcp_oauth_clients_registration_method_check"),)


class McpOAuthGrant(Base):
    __tablename__ = "mcp_oauth_grants"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_host: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    display_name: Mapped[str | None] = mapped_column(String(100))
    scope_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))

    __table_args__ = (Index("idx_mcp_oauth_grants_active_user", "user_id", desc("created_at"), postgresql_where=text("revoked_at IS NULL")),)


class McpOAuthUserClient(Base):
    __tablename__ = "mcp_oauth_user_clients"

    client_id: Mapped[str] = mapped_column(Text, ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    label: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (CheckConstraint("provider IN ('claude', 'manual')", name="mcp_oauth_user_clients_provider_check"),)


class McpOAuthAuthorizationCode(Base):
    __tablename__ = "mcp_oauth_authorization_codes"

    code_digest: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    grant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("mcp_oauth_grants.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (Index("idx_mcp_oauth_codes_expiry", "expires_at"),)


class McpOAuthToken(Base):
    __tablename__ = "mcp_oauth_tokens"

    token_digest: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    grant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("mcp_oauth_grants.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    token_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("token_type IN ('access', 'refresh')", name="mcp_oauth_tokens_token_type_check"),
        Index("idx_mcp_oauth_tokens_active_grant", "grant_id", "token_type", "expires_at", postgresql_where=text("revoked_at IS NULL")),
    )
