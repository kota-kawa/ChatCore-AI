"""Fix CASE expression in version trigger functions.

The previous migration used `CASE TG_OP WHEN <boolean-expr>`, which is
invalid PostgreSQL: a simple CASE compares the selector (TG_OP, type text)
to each WHEN value, so a boolean condition causes
"operator does not exist: text = boolean".

This migration replaces both trigger functions with a searched CASE that
uses explicit `WHEN TG_OP = '...'` comparisons.

Revision ID: 20260322_04
Revises: 20260322_03
Create Date: 2026-03-22 13:00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260322_04"
down_revision: Union[str, Sequence[str], None] = "20260322_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
                source_deleted_at
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
                COALESCE(NEW.user_id, OLD.user_id),
                COALESCE(NEW.name, OLD.name),
                COALESCE(NEW.prompt_template, OLD.prompt_template),
                COALESCE(NEW.response_rules, OLD.response_rules),
                COALESCE(NEW.output_skeleton, OLD.output_skeleton),
                COALESCE(NEW.input_examples, OLD.input_examples),
                COALESCE(NEW.output_examples, OLD.output_examples),
                COALESCE(NEW.display_order, OLD.display_order),
                COALESCE(NEW.created_at, OLD.created_at),
                COALESCE(NEW.updated_at, OLD.updated_at),
                COALESCE(NEW.deleted_at, OLD.deleted_at)
            );

            RETURN COALESCE(NEW, OLD);
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
                source_deleted_at
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
                COALESCE(NEW.user_id, OLD.user_id),
                COALESCE(NEW.is_public, OLD.is_public),
                COALESCE(NEW.title, OLD.title),
                COALESCE(NEW.category, OLD.category),
                COALESCE(NEW.content, OLD.content),
                COALESCE(NEW.author, OLD.author),
                COALESCE(NEW.input_examples, OLD.input_examples),
                COALESCE(NEW.output_examples, OLD.output_examples),
                COALESCE(NEW.created_at, OLD.created_at),
                COALESCE(NEW.updated_at, OLD.updated_at),
                COALESCE(NEW.deleted_at, OLD.deleted_at)
            );

            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    # Restore the original (buggy) function bodies — kept only for Alembic
    # chain completeness; these functions should not be deployed.
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
                source_deleted_at
            )
            VALUES (
                COALESCE(NEW.id, OLD.id),
                next_version,
                CASE TG_OP
                    WHEN 'INSERT' THEN 'created'
                    WHEN 'DELETE' THEN 'deleted'
                    ELSE 'updated'
                END,
                COALESCE(NEW.user_id, OLD.user_id),
                COALESCE(NEW.name, OLD.name),
                COALESCE(NEW.prompt_template, OLD.prompt_template),
                COALESCE(NEW.response_rules, OLD.response_rules),
                COALESCE(NEW.output_skeleton, OLD.output_skeleton),
                COALESCE(NEW.input_examples, OLD.input_examples),
                COALESCE(NEW.output_examples, OLD.output_examples),
                COALESCE(NEW.display_order, OLD.display_order),
                COALESCE(NEW.created_at, OLD.created_at),
                COALESCE(NEW.updated_at, OLD.updated_at),
                COALESCE(NEW.deleted_at, OLD.deleted_at)
            );

            RETURN COALESCE(NEW, OLD);
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
                source_deleted_at
            )
            VALUES (
                COALESCE(NEW.id, OLD.id),
                next_version,
                CASE TG_OP
                    WHEN 'INSERT' THEN 'created'
                    WHEN 'DELETE' THEN 'deleted'
                    ELSE 'updated'
                END,
                COALESCE(NEW.user_id, OLD.user_id),
                COALESCE(NEW.is_public, OLD.is_public),
                COALESCE(NEW.title, OLD.title),
                COALESCE(NEW.category, OLD.category),
                COALESCE(NEW.content, OLD.content),
                COALESCE(NEW.author, OLD.author),
                COALESCE(NEW.input_examples, OLD.input_examples),
                COALESCE(NEW.output_examples, OLD.output_examples),
                COALESCE(NEW.created_at, OLD.created_at),
                COALESCE(NEW.updated_at, OLD.updated_at),
                COALESCE(NEW.deleted_at, OLD.deleted_at)
            );

            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql
        """
    )
