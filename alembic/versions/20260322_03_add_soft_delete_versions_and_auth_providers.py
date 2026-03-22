"""Add soft delete, version history, and auth providers table.

Revision ID: 20260322_03
Revises: 20260322_02
Create Date: 2026-03-22 12:30:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260322_03"
down_revision: Union[str, Sequence[str], None] = "20260322_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE task_with_examples
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL
        """
    )
    op.execute(
        """
        UPDATE prompts
           SET updated_at = created_at
         WHERE updated_at IS NULL
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_with_examples_active_user_order
            ON task_with_examples (user_id, display_order, id)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_with_examples_active_user_name
            ON task_with_examples (user_id, name)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_active_public_created_at
            ON prompts (is_public, created_at DESC)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_active_user_created_at
            ON prompts (user_id, created_at DESC)
            WHERE deleted_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS task_versions (
            id SERIAL PRIMARY KEY,
            task_id INT NOT NULL,
            version_number INT NOT NULL,
            operation VARCHAR(16) NOT NULL,
            user_id INT NULL,
            name VARCHAR(255) NOT NULL,
            prompt_template TEXT NOT NULL,
            response_rules TEXT NULL,
            output_skeleton TEXT NULL,
            input_examples TEXT NULL,
            output_examples TEXT NULL,
            display_order INT NULL,
            source_created_at TIMESTAMP NULL,
            source_updated_at TIMESTAMP NULL,
            source_deleted_at TIMESTAMP NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_task_versions_task
                FOREIGN KEY (task_id)
                REFERENCES task_with_examples(id)
                ON DELETE CASCADE,
            CONSTRAINT uq_task_versions_task_version
                UNIQUE (task_id, version_number)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_versions_task_created_at
            ON task_versions (task_id, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_versions (
            id SERIAL PRIMARY KEY,
            prompt_id INT NOT NULL,
            version_number INT NOT NULL,
            operation VARCHAR(16) NOT NULL,
            user_id INT NOT NULL,
            is_public BOOLEAN NOT NULL,
            title VARCHAR(255) NOT NULL,
            category VARCHAR(50) NOT NULL,
            content TEXT NOT NULL,
            author VARCHAR(50) NOT NULL,
            input_examples TEXT NULL,
            output_examples TEXT NULL,
            source_created_at TIMESTAMP NULL,
            source_updated_at TIMESTAMP NULL,
            source_deleted_at TIMESTAMP NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_prompt_versions_prompt
                FOREIGN KEY (prompt_id)
                REFERENCES prompts(id)
                ON DELETE CASCADE,
            CONSTRAINT uq_prompt_versions_prompt_version
                UNIQUE (prompt_id, version_number)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_versions_prompt_created_at
            ON prompt_versions (prompt_id, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_auth_providers (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            provider VARCHAR(32) NOT NULL,
            provider_user_id VARCHAR(255) NULL,
            provider_email VARCHAR(255) NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_user_auth_providers_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,
            CONSTRAINT uq_user_auth_providers_user_provider
                UNIQUE (user_id, provider)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_user_auth_providers_provider_identity
            ON user_auth_providers (provider, provider_user_id)
            WHERE provider_user_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_auth_providers_user_provider
            ON user_auth_providers (user_id, provider)
        """
    )

    op.execute(
        """
        INSERT INTO user_auth_providers (
            user_id,
            provider,
            provider_user_id,
            provider_email
        )
        SELECT
            id,
            auth_provider,
            CASE
                WHEN auth_provider = 'email' THEN COALESCE(NULLIF(provider_user_id, ''), email)
                ELSE NULLIF(provider_user_id, '')
            END,
            COALESCE(NULLIF(provider_email, ''), email)
        FROM users
        ON CONFLICT (user_id, provider) DO UPDATE
           SET provider_user_id = EXCLUDED.provider_user_id,
               provider_email = EXCLUDED.provider_email,
               updated_at = CURRENT_TIMESTAMP
        """
    )
    op.execute(
        """
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
            created_at
        )
        SELECT
            t.id,
            1,
            CASE WHEN t.deleted_at IS NULL THEN 'created' ELSE 'deleted' END,
            t.user_id,
            t.name,
            t.prompt_template,
            t.response_rules,
            t.output_skeleton,
            t.input_examples,
            t.output_examples,
            t.display_order,
            t.created_at,
            t.updated_at,
            t.deleted_at,
            COALESCE(t.updated_at, t.created_at, CURRENT_TIMESTAMP)
        FROM task_with_examples AS t
        WHERE NOT EXISTS (
            SELECT 1
              FROM task_versions AS tv
             WHERE tv.task_id = t.id
        )
        """
    )
    op.execute(
        """
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
            created_at
        )
        SELECT
            p.id,
            1,
            CASE WHEN p.deleted_at IS NULL THEN 'created' ELSE 'deleted' END,
            p.user_id,
            p.is_public,
            p.title,
            p.category,
            p.content,
            p.author,
            p.input_examples,
            p.output_examples,
            p.created_at,
            p.updated_at,
            p.deleted_at,
            COALESCE(p.updated_at, p.created_at, CURRENT_TIMESTAMP)
        FROM prompts AS p
        WHERE NOT EXISTS (
            SELECT 1
              FROM prompt_versions AS pv
             WHERE pv.prompt_id = p.id
        )
        """
    )

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
                    WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN 'deleted'
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
                    WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN 'deleted'
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

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_prompts_updated_at'
                  AND tgrelid = 'prompts'::regclass
            ) THEN
                CREATE TRIGGER trg_prompts_updated_at
                BEFORE UPDATE ON prompts
                FOR EACH ROW
                EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_user_auth_providers_updated_at'
                  AND tgrelid = 'user_auth_providers'::regclass
            ) THEN
                CREATE TRIGGER trg_user_auth_providers_updated_at
                BEFORE UPDATE ON user_auth_providers
                FOR EACH ROW
                EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_task_versions_record'
                  AND tgrelid = 'task_with_examples'::regclass
            ) THEN
                CREATE TRIGGER trg_task_versions_record
                AFTER INSERT OR UPDATE OR DELETE ON task_with_examples
                FOR EACH ROW
                EXECUTE FUNCTION record_task_version();
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_prompt_versions_record'
                  AND tgrelid = 'prompts'::regclass
            ) THEN
                CREATE TRIGGER trg_prompt_versions_record
                AFTER INSERT OR UPDATE OR DELETE ON prompts
                FOR EACH ROW
                EXECUTE FUNCTION record_prompt_version();
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        ALTER TABLE users
            DROP COLUMN IF EXISTS auth_provider,
            DROP COLUMN IF EXISTS provider_user_id,
            DROP COLUMN IF EXISTS provider_email
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_users_provider_identity")
    op.execute("DROP INDEX IF EXISTS idx_task_with_examples_active_user_order")
    op.execute("DROP INDEX IF EXISTS idx_task_with_examples_active_user_name")
    op.execute("DROP INDEX IF EXISTS idx_prompts_active_public_created_at")
    op.execute("DROP INDEX IF EXISTS idx_prompts_active_user_created_at")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_with_examples_active_user_order
            ON task_with_examples (user_id, display_order, id)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_with_examples_active_user_name
            ON task_with_examples (user_id, name)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_active_public_created_at
            ON prompts (is_public, created_at DESC)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_active_user_created_at
            ON prompts (user_id, created_at DESC)
            WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_prompt_versions_record ON prompts")
    op.execute("DROP TRIGGER IF EXISTS trg_task_versions_record ON task_with_examples")
    op.execute("DROP TRIGGER IF EXISTS trg_user_auth_providers_updated_at ON user_auth_providers")
    op.execute("DROP TRIGGER IF EXISTS trg_prompts_updated_at ON prompts")
    op.execute("DROP FUNCTION IF EXISTS record_prompt_version()")
    op.execute("DROP FUNCTION IF EXISTS record_task_version()")
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(32) NOT NULL DEFAULT 'email',
            ADD COLUMN IF NOT EXISTS provider_user_id VARCHAR(255) NULL,
            ADD COLUMN IF NOT EXISTS provider_email VARCHAR(255) NULL
        """
    )
    op.execute(
        """
        WITH ranked_providers AS (
            SELECT
                user_id,
                provider,
                provider_user_id,
                provider_email,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY CASE WHEN provider = 'google' THEN 0 ELSE 1 END, id
                ) AS provider_rank
            FROM user_auth_providers
        )
        UPDATE users AS u
           SET auth_provider = rp.provider,
               provider_user_id = rp.provider_user_id,
               provider_email = rp.provider_email
          FROM ranked_providers AS rp
         WHERE u.id = rp.user_id
           AND rp.provider_rank = 1
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_provider_identity
            ON users (auth_provider, provider_user_id)
            WHERE provider_user_id IS NOT NULL
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_user_auth_providers_provider_identity")
    op.execute("DROP TABLE IF EXISTS user_auth_providers")
    op.execute("DROP TABLE IF EXISTS prompt_versions")
    op.execute("DROP TABLE IF EXISTS task_versions")
    op.execute("DROP INDEX IF EXISTS idx_prompts_active_user_created_at")
    op.execute("DROP INDEX IF EXISTS idx_prompts_active_public_created_at")
    op.execute("DROP INDEX IF EXISTS idx_task_with_examples_active_user_name")
    op.execute("DROP INDEX IF EXISTS idx_task_with_examples_active_user_order")
    op.execute(
        """
        ALTER TABLE task_with_examples
            DROP COLUMN IF EXISTS deleted_at
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
            DROP COLUMN IF EXISTS deleted_at,
            DROP COLUMN IF EXISTS updated_at
        """
    )
