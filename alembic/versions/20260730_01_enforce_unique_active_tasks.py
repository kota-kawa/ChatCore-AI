"""Prevent duplicate active task definitions.

Revision ID: 20260730_01
Revises: 20260728_02
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_01"
down_revision: Union[str, Sequence[str], None] = "20260728_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Deduplicate active tasks without discarding distinct user content."""
    op.add_column(
        "task_with_examples",
        sa.Column(
            "is_system_task_customized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Exact active duplicates are recoverably soft-deleted. Display order and
    # timestamps are intentionally excluded because they do not change the task
    # definition itself.
    op.execute(
        """
        WITH duplicate_groups AS (
            SELECT user_id,
                   LOWER(BTRIM(name)) AS normalized_name,
                   prompt_template,
                   COALESCE(response_rules, '') AS response_rules,
                   COALESCE(output_skeleton, '') AS output_skeleton,
                   COALESCE(input_examples, '') AS input_examples,
                   COALESCE(output_examples, '') AS output_examples
              FROM task_with_examples
             WHERE deleted_at IS NULL
             GROUP BY user_id,
                      LOWER(BTRIM(name)),
                      prompt_template,
                      COALESCE(response_rules, ''),
                      COALESCE(output_skeleton, ''),
                      COALESCE(input_examples, ''),
                      COALESCE(output_examples, '')
            HAVING COUNT(*) > 1
               AND COUNT(DISTINCT system_task_key) <= 1
               AND COUNT(DISTINCT source_prompt_id) <= 1
        ),
        ranked_duplicates AS (
            SELECT task.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY task.user_id,
                                    LOWER(BTRIM(task.name)),
                                    task.prompt_template,
                                    COALESCE(task.response_rules, ''),
                                    COALESCE(task.output_skeleton, ''),
                                    COALESCE(task.input_examples, ''),
                                    COALESCE(task.output_examples, '')
                       ORDER BY CASE
                                    WHEN task.system_task_key IS NOT NULL
                                      OR task.source_prompt_id IS NOT NULL
                                    THEN 0 ELSE 1
                                END,
                                task.created_at ASC NULLS LAST,
                                task.id ASC
                   ) AS duplicate_number
              FROM task_with_examples AS task
              JOIN duplicate_groups AS duplicate_group
                ON task.user_id IS NOT DISTINCT FROM duplicate_group.user_id
               AND LOWER(BTRIM(task.name)) = duplicate_group.normalized_name
               AND task.prompt_template = duplicate_group.prompt_template
               AND COALESCE(task.response_rules, '') = duplicate_group.response_rules
               AND COALESCE(task.output_skeleton, '') = duplicate_group.output_skeleton
               AND COALESCE(task.input_examples, '') = duplicate_group.input_examples
               AND COALESCE(task.output_examples, '') = duplicate_group.output_examples
             WHERE task.deleted_at IS NULL
        )
        UPDATE task_with_examples AS task
           SET deleted_at = CURRENT_TIMESTAMP
          FROM ranked_duplicates AS duplicate
         WHERE task.id = duplicate.id
           AND duplicate.duplicate_number > 1
        """
    )

    # Replace the unsafe runtime title fallback with a one-time conservative
    # backfill. Only a single public prompt whose complete legacy task payload
    # matches is accepted; ambiguous titles/content remain standalone tasks.
    op.execute(
        """
        WITH prompt_matches AS (
            SELECT task.id AS task_id,
                   MIN(prompt.id) AS prompt_id,
                   COUNT(*) AS match_count
              FROM task_with_examples AS task
              JOIN prompts AS prompt
                ON prompt.title = task.name
               AND prompt.content = task.prompt_template
               AND COALESCE(prompt.input_examples, '') = COALESCE(task.input_examples, '')
               AND COALESCE(prompt.output_examples, '') = COALESCE(task.output_examples, '')
               AND prompt.is_public = TRUE
               AND prompt.deleted_at IS NULL
             WHERE task.user_id IS NOT NULL
               AND task.deleted_at IS NULL
               AND task.source_prompt_id IS NULL
             GROUP BY task.id
        )
        UPDATE task_with_examples AS task
           SET source_prompt_id = matched.prompt_id
          FROM prompt_matches AS matched
         WHERE task.id = matched.task_id
           AND matched.match_count = 1
           AND NOT EXISTS (
               SELECT 1
                 FROM task_with_examples AS existing
                WHERE existing.user_id = task.user_id
                  AND existing.source_prompt_id = matched.prompt_id
                  AND existing.deleted_at IS NULL
           )
        """
    )

    # If differing rows share provenance, retain the oldest row as the canonical
    # imported/system task and detach the others so no user-authored content is lost.
    op.execute(
        """
        WITH ranked_system_tasks AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id, system_task_key
                       ORDER BY created_at ASC NULLS LAST, id ASC
                   ) AS provenance_number
              FROM task_with_examples
             WHERE deleted_at IS NULL
               AND system_task_key IS NOT NULL
        )
        UPDATE task_with_examples AS task
           SET system_task_key = NULL,
               is_system_task_customized = TRUE
          FROM ranked_system_tasks AS ranked
         WHERE task.id = ranked.id
           AND ranked.provenance_number > 1
        """
    )
    op.execute(
        """
        WITH ranked_prompt_tasks AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id, source_prompt_id
                       ORDER BY created_at ASC NULLS LAST, id ASC
                   ) AS provenance_number
              FROM task_with_examples
             WHERE deleted_at IS NULL
               AND user_id IS NOT NULL
               AND source_prompt_id IS NOT NULL
        )
        UPDATE task_with_examples AS task
           SET source_prompt_id = NULL
          FROM ranked_prompt_tasks AS ranked
         WHERE task.id = ranked.id
           AND ranked.provenance_number > 1
        """
    )

    # Same-name tasks with different contents remain active. Give every later row
    # a deterministic, collision-free suffix before enforcing normalized names.
    op.execute(
        """
        DO $$
        DECLARE
            duplicate_task RECORD;
            suffix_number INTEGER;
            suffix TEXT;
            candidate_name TEXT;
        BEGIN
            FOR duplicate_task IN
                SELECT id, user_id, name
                  FROM (
                      SELECT id,
                             user_id,
                             name,
                             ROW_NUMBER() OVER (
                                 PARTITION BY user_id, LOWER(BTRIM(name))
                                 ORDER BY created_at ASC NULLS LAST, id ASC
                             ) AS name_number
                       FROM task_with_examples
                       WHERE deleted_at IS NULL
                  ) AS ranked_names
                 WHERE name_number > 1
                 ORDER BY user_id, id
            LOOP
                suffix_number := 2;
                LOOP
                    suffix := FORMAT(' (%s)', suffix_number);
                    candidate_name := LEFT(
                        BTRIM(duplicate_task.name),
                        255 - CHAR_LENGTH(suffix)
                    ) || suffix;

                    EXIT WHEN NOT EXISTS (
                        SELECT 1
                          FROM task_with_examples AS existing
                         WHERE (
                               existing.user_id = duplicate_task.user_id
                               OR (
                                   existing.user_id IS NULL
                                   AND duplicate_task.user_id IS NULL
                               )
                           )
                           AND existing.deleted_at IS NULL
                           AND existing.id <> duplicate_task.id
                           AND LOWER(BTRIM(existing.name)) = LOWER(BTRIM(candidate_name))
                    );
                    suffix_number := suffix_number + 1;
                END LOOP;

                UPDATE task_with_examples
                   SET name = candidate_name
                 WHERE id = duplicate_task.id;
            END LOOP;
        END $$
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_task_with_examples_active_user_normalized_name
            ON task_with_examples (user_id, LOWER(BTRIM(name)))
         WHERE user_id IS NOT NULL
           AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_task_with_examples_active_shared_normalized_name
            ON task_with_examples (LOWER(BTRIM(name)))
         WHERE user_id IS NULL
           AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_task_with_examples_active_user_system_key
            ON task_with_examples (user_id, system_task_key)
         WHERE user_id IS NOT NULL
           AND system_task_key IS NOT NULL
           AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_task_with_examples_active_shared_system_key
            ON task_with_examples (system_task_key)
         WHERE user_id IS NULL
           AND system_task_key IS NOT NULL
           AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_task_with_examples_active_user_source_prompt
            ON task_with_examples (user_id, source_prompt_id)
         WHERE user_id IS NOT NULL
           AND source_prompt_id IS NOT NULL
           AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    """Remove duplicate-prevention constraints; data cleanup is not reversed."""
    op.execute("DROP INDEX IF EXISTS uq_task_with_examples_active_user_source_prompt")
    op.execute("DROP INDEX IF EXISTS uq_task_with_examples_active_shared_system_key")
    op.execute("DROP INDEX IF EXISTS uq_task_with_examples_active_user_system_key")
    op.execute("DROP INDEX IF EXISTS uq_task_with_examples_active_shared_normalized_name")
    op.execute("DROP INDEX IF EXISTS uq_task_with_examples_active_user_normalized_name")
    op.drop_column("task_with_examples", "is_system_task_customized")
