"""Harden version history, guest ownership, and embedding recovery contracts.

Revision ID: 20260826_01
Revises: 20260824_03
Create Date: 2026-08-26

The version tables were created before guest prompts and several prompt/task
fields were introduced. Keep the legacy columns for readers that still use
them, but store a complete row snapshot for every new revision. The prompt
history owner is nullable because an unclaimed guest prompt has no user yet.

The embedding status columns make rows skipped by the legacy vector migration
observable and allow the backfill command to report a deterministic queue.

# migration-review: approved-data-backfill
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260826_01"
down_revision: Union[str, Sequence[str], None] = "20260824_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_legacy_snapshots() -> None:
    """Represent pre-snapshot history with every field that existed then."""
    op.execute(
        """
        UPDATE task_versions
           SET snapshot = jsonb_build_object(
                   'id', id,
                   'task_id', task_id,
                   'version_number', version_number,
                   'operation', operation,
                   'user_id', user_id,
                   'name', name,
                   'prompt_template', prompt_template,
                   'response_rules', response_rules,
                   'output_skeleton', output_skeleton,
                   'input_examples', input_examples,
                   'output_examples', output_examples,
                   'display_order', display_order,
                   'created_at', source_created_at,
                   'updated_at', source_updated_at,
                   'deleted_at', source_deleted_at
               )
         WHERE snapshot = '{}'::jsonb
        """
    )
    op.execute(
        """
        UPDATE prompt_versions
           SET snapshot = jsonb_build_object(
                   'id', id,
                   'prompt_id', prompt_id,
                   'version_number', version_number,
                   'operation', operation,
                   'user_id', user_id,
                   'is_public', is_public,
                   'title', title,
                   'category', category,
                   'content', content,
                   'author', author,
                   'input_examples', input_examples,
                   'output_examples', output_examples,
                   'created_at', source_created_at,
                   'updated_at', source_updated_at,
                   'deleted_at', source_deleted_at
               )
         WHERE snapshot = '{}'::jsonb
        """
    )


def _replace_version_triggers() -> None:
    """Record explicit NULLs and a full row image without changing trigger timing."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION record_task_version()
        RETURNS TRIGGER AS $$
        DECLARE
            next_version INT;
        BEGIN
            SELECT COALESCE(MAX(version_number), 0) + 1
              INTO next_version
              FROM task_versions
             WHERE task_id = COALESCE(NEW.id, OLD.id);

            INSERT INTO task_versions (
                task_id,
                version_number,
                operation,
                user_id,
                name,
                prompt_template,
                response_rules,
                output_skeleton,
                input_examples,
                output_examples,
                display_order,
                source_created_at,
                source_updated_at,
                source_deleted_at,
                snapshot
            )
            VALUES (
                COALESCE(NEW.id, OLD.id),
                next_version,
                CASE
                    WHEN TG_OP = 'INSERT' THEN 'created'
                    WHEN TG_OP = 'DELETE' THEN 'deleted'
                    WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN 'soft_deleted'
                    ELSE 'updated'
                END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.user_id ELSE NEW.user_id END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.name ELSE NEW.name END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.prompt_template ELSE NEW.prompt_template END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.response_rules ELSE NEW.response_rules END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.output_skeleton ELSE NEW.output_skeleton END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.input_examples ELSE NEW.input_examples END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.output_examples ELSE NEW.output_examples END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.display_order ELSE NEW.display_order END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.created_at ELSE NEW.created_at END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.updated_at ELSE NEW.updated_at END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.deleted_at ELSE NEW.deleted_at END,
                CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END
            );

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION record_prompt_version()
        RETURNS TRIGGER AS $$
        DECLARE
            next_version INT;
        BEGIN
            SELECT COALESCE(MAX(version_number), 0) + 1
              INTO next_version
              FROM prompt_versions
             WHERE prompt_id = COALESCE(NEW.id, OLD.id);

            INSERT INTO prompt_versions (
                prompt_id,
                version_number,
                operation,
                user_id,
                is_public,
                title,
                category,
                content,
                author,
                input_examples,
                output_examples,
                source_created_at,
                source_updated_at,
                source_deleted_at,
                snapshot
            )
            VALUES (
                COALESCE(NEW.id, OLD.id),
                next_version,
                CASE
                    WHEN TG_OP = 'INSERT' THEN 'created'
                    WHEN TG_OP = 'DELETE' THEN 'deleted'
                    WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN 'soft_deleted'
                    ELSE 'updated'
                END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.user_id ELSE NEW.user_id END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.is_public ELSE NEW.is_public END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.title ELSE NEW.title END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.category ELSE NEW.category END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.content ELSE NEW.content END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.author ELSE NEW.author END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.input_examples ELSE NEW.input_examples END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.output_examples ELSE NEW.output_examples END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.created_at ELSE NEW.created_at END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.updated_at ELSE NEW.updated_at END,
                CASE WHEN TG_OP = 'DELETE' THEN OLD.deleted_at ELSE NEW.deleted_at END,
                CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END
            );

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def upgrade() -> None:
    """Add compatible history snapshots and observable embedding work queues."""
    op.alter_column(
        "prompt_versions",
        "user_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column(
        "task_versions",
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "prompt_versions",
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    _backfill_legacy_snapshots()
    _replace_version_triggers()

    op.add_column(
        "memo_entries",
        sa.Column(
            "embedding_status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    op.add_column(
        "context_facts",
        sa.Column(
            "embedding_status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    op.create_check_constraint(
        "ck_memo_entries_embedding_status",
        "memo_entries",
        "embedding_status IN ('pending', 'ready')",
    )
    op.create_check_constraint(
        "ck_context_facts_embedding_status",
        "context_facts",
        "embedding_status IN ('pending', 'ready')",
    )
    op.execute(
        """
        UPDATE memo_entries
           SET embedding_status = 'ready'
         WHERE embedding_vector IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE context_facts
           SET embedding_status = 'ready'
         WHERE embedding_vector IS NOT NULL
        """
    )


def downgrade() -> None:
    """Refuse an automatic downgrade because it would discard snapshots/status."""
    raise RuntimeError(
        "20260826_01 is intentionally irreversible: back up and perform a reviewed "
        "contract migration before removing history snapshots or embedding status."
    )
