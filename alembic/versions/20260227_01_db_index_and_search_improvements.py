"""Bootstrap core schema and add index improvements.

Revision ID: 20260227_01
Revises:
Create Date: 2026-02-27 06:15:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260227_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    [JP] データベースのコアスキーマをブートストラップし、検索およびインデックスの改善を適用します。
    [EN] Bootstrap the core database schema and apply index and search improvements.
    """
    # [JP] pg_trgm 拡張機能の作成 (トリグラム検索用)
    # [EN] Create pg_trgm extension for trigram search
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # [JP] users テーブルの作成
    # [EN] Create users table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            username VARCHAR(255) NOT NULL DEFAULT 'ユーザー',
            bio TEXT NULL,
            avatar_url VARCHAR(255) NOT NULL DEFAULT '/static/user-icon.png',
            is_verified BOOLEAN DEFAULT FALSE,
            auth_provider VARCHAR(32) NOT NULL DEFAULT 'email',
            provider_user_id VARCHAR(255) NULL,
            provider_email VARCHAR(255) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # [JP] 外部プロバイダー連携用のユニークインデックス
    # [EN] Unique index for external auth provider integration
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_provider_identity
            ON users (auth_provider, provider_user_id)
            WHERE provider_user_id IS NOT NULL
        """
    )

    # [JP] user_passkeys テーブルの作成
    # [EN] Create user_passkeys table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_passkeys (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            credential_id VARCHAR(255) NOT NULL UNIQUE,
            public_key TEXT NOT NULL,
            sign_count BIGINT NOT NULL DEFAULT 0,
            aaguid VARCHAR(64) NULL,
            credential_device_type VARCHAR(32) NULL,
            credential_backed_up BOOLEAN NOT NULL DEFAULT FALSE,
            label VARCHAR(255) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP NULL,
            CONSTRAINT fk_user_passkeys_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
        """
    )
    # [JP] パスキーのユーザーIDおよび作成日時インデックス
    # [EN] Index for user_passkeys by user_id and created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_passkeys_user_created_at
            ON user_passkeys (user_id, created_at DESC)
        """
    )

    # [JP] chat_rooms テーブルの作成
    # [EN] Create chat_rooms table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_rooms (
            id VARCHAR(255) PRIMARY KEY,
            user_id INT NOT NULL,
            title VARCHAR(255) DEFAULT '新規チャット',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_chat_rooms_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
        """
    )
    # [JP] チャットルームのユーザーIDおよび作成日時インデックス
    # [EN] Index for chat_rooms by user_id and created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_rooms_user_created_at
            ON chat_rooms (user_id, created_at DESC)
        """
    )

    # [JP] chat_history テーブルの作成
    # [EN] Create chat_history table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_history (
            id SERIAL PRIMARY KEY,
            chat_room_id VARCHAR(255) NOT NULL,
            message TEXT,
            sender VARCHAR(20) CHECK (sender IN ('user','assistant')),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_chat_history_room
                FOREIGN KEY (chat_room_id)
                REFERENCES chat_rooms(id)
                ON DELETE CASCADE
        )
        """
    )
    # [JP] チャット履歴のルームIDおよびIDインデックス
    # [EN] Index for chat_history by chat_room_id and id
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_history_room_id_id
            ON chat_history (chat_room_id, id)
        """
    )

    # [JP] shared_chat_rooms テーブルの作成
    # [EN] Create shared_chat_rooms table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shared_chat_rooms (
            id SERIAL PRIMARY KEY,
            chat_room_id VARCHAR(255) NOT NULL UNIQUE,
            share_token VARCHAR(128) NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_shared_chat_rooms_room
                FOREIGN KEY (chat_room_id)
                REFERENCES chat_rooms(id)
                ON DELETE CASCADE
        )
        """
    )
    # [JP] 共有チャットのトークンおよび作成日時インデックス
    # [EN] Index for shared_chat_rooms by share_token and created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_shared_chat_rooms_token_created_at
            ON shared_chat_rooms (share_token, created_at DESC)
        """
    )

    # [JP] task_with_examples テーブルの作成
    # [EN] Create task_with_examples table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS task_with_examples (
            id SERIAL PRIMARY KEY,
            user_id INT NULL,
            name VARCHAR(255) NOT NULL,
            prompt_template TEXT NOT NULL,
            response_rules TEXT,
            output_skeleton TEXT,
            input_examples TEXT,
            output_examples TEXT,
            display_order INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_task_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
        """
    )
    # [JP] タスクのユーザーIDおよび名前インデックス
    # [EN] Index for task_with_examples by user_id and name
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_with_examples_user_name
            ON task_with_examples (user_id, name)
        """
    )
    # [JP] タスクの表示順序インデックス
    # [EN] Index for task_with_examples by display_order
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_with_examples_user_order
            ON task_with_examples (user_id, display_order, id)
        """
    )
    # [JP] タスクの作成日時インデックス
    # [EN] Index for task_with_examples by created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_with_examples_user_created_at
            ON task_with_examples (user_id, created_at DESC, id DESC)
        """
    )

    # [JP] prompts テーブルの作成
    # [EN] Create prompts table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompts (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            is_public BOOLEAN NOT NULL DEFAULT FALSE,
            title VARCHAR(255) NOT NULL,
            category VARCHAR(50) NOT NULL,
            content TEXT NOT NULL,
            author VARCHAR(50) NOT NULL,
            input_examples TEXT,
            output_examples TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_prompts_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
        """
    )
    # [JP] 公開プロンプトインデックス
    # [EN] Index for public prompts by created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_public_created_at
            ON prompts (is_public, created_at DESC)
        """
    )
    # [JP] ユーザーのプロンプトインデックス
    # [EN] Index for user prompts by created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_user_created_at
            ON prompts (user_id, created_at DESC)
        """
    )
    # [JP] タイトル、コンテンツ、カテゴリ、作者に対する pg_trgm GIN インデックス (部分一致検索高速化)
    # [EN] GIN indexes on title, content, category, and author using pg_trgm for fast text search
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_public_title_trgm
            ON prompts USING gin (title gin_trgm_ops)
            WHERE is_public = TRUE
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_public_content_trgm
            ON prompts USING gin (content gin_trgm_ops)
            WHERE is_public = TRUE
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_public_category_trgm
            ON prompts USING gin (category gin_trgm_ops)
            WHERE is_public = TRUE
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_public_author_trgm
            ON prompts USING gin (author gin_trgm_ops)
            WHERE is_public = TRUE
        """
    )

    # [JP] prompt_list_entries テーブルの作成
    # [EN] Create prompt_list_entries table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_list_entries (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            prompt_id INT NULL,
            title VARCHAR(255) NOT NULL,
            category VARCHAR(50) DEFAULT '',
            content TEXT NOT NULL,
            input_examples TEXT,
            output_examples TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, prompt_id),
            CONSTRAINT fk_prompt_list_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_prompt_list_prompt
                FOREIGN KEY (prompt_id)
                REFERENCES prompts(id)
                ON DELETE SET NULL
        )
        """
    )
    # [JP] プロンプト登録項目のタイトルインデックス
    # [EN] Index for prompt list entries by user_id and title
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_list_user_title
            ON prompt_list_entries (user_id, title)
        """
    )
    # [JP] プロンプト登録項目の作成日時インデックス
    # [EN] Index for prompt list entries by user_id and created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_list_user_created_at
            ON prompt_list_entries (user_id, created_at DESC, id DESC)
        """
    )
    # [JP] prompt_id が NULL の場合、ユーザーごとにタイトルが一意であることを担保する部分インデックス
    # [EN] Unique partial index ensuring unique title per user when prompt_id is NULL
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = 'uq_prompt_list_user_title_when_prompt_null'
            ) THEN
                IF EXISTS (
                    SELECT 1
                    FROM prompt_list_entries
                    WHERE prompt_id IS NULL
                    GROUP BY user_id, title
                    HAVING COUNT(*) > 1
                ) THEN
                    RAISE EXCEPTION
                        'Cannot create uq_prompt_list_user_title_when_prompt_null due to duplicate rows.';
                END IF;
                CREATE UNIQUE INDEX uq_prompt_list_user_title_when_prompt_null
                    ON prompt_list_entries (user_id, title)
                    WHERE prompt_id IS NULL;
            END IF;
        END $$;
        """
    )

    # [JP] memo_entries テーブルの作成
    # [EN] Create memo_entries table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memo_entries (
            id SERIAL PRIMARY KEY,
            user_id INT NULL,
            input_content TEXT NOT NULL,
            ai_response TEXT NOT NULL,
            title VARCHAR(255) NOT NULL,
            tags VARCHAR(255) DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_memo_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
        """
    )
    # [JP] メモの作成日時インデックス
    # [EN] Index for memo_entries by created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memo_entries_created_at
            ON memo_entries (created_at DESC)
        """
    )
    # [JP] ユーザー別のメモ作成日時インデックス
    # [EN] Index for memo_entries by user_id and created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memo_entries_user_created_at
            ON memo_entries (user_id, created_at DESC)
        """
    )

    # [JP] updated_at カラムを自動更新する共通関数の作成
    # [EN] Create helper function to update updated_at timestamp automatically
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
          NEW.updated_at = CURRENT_TIMESTAMP;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    # [JP] task_with_examples テーブルに対する updated_at トリガーの設定
    # [EN] Set up trigger for task_with_examples table to update updated_at
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_task_with_examples_updated_at'
                  AND tgrelid = 'task_with_examples'::regclass
            ) THEN
                CREATE TRIGGER trg_task_with_examples_updated_at
                BEFORE UPDATE ON task_with_examples
                FOR EACH ROW
                EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
        """
    )
    # [JP] memo_entries テーブルに対する updated_at トリガーの設定
    # [EN] Set up trigger for memo_entries table to update updated_at
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_memo_entries_updated_at'
                  AND tgrelid = 'memo_entries'::regclass
            ) THEN
                CREATE TRIGGER trg_memo_entries_updated_at
                BEFORE UPDATE ON memo_entries
                FOR EACH ROW
                EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """
    [JP] データベースのコアスキーマを削除し、bootstrap前の状態に戻します。
    [EN] Drop the core database schema and revert to the state before bootstrapping.
    """
    # [JP] 各トリガー、関数、テーブルおよびインデックスの削除
    # [EN] Drop triggers, functions, tables, and indexes in reverse order of creation
    op.execute("DROP TRIGGER IF EXISTS trg_memo_entries_updated_at ON memo_entries")
    op.execute("DROP TRIGGER IF EXISTS trg_task_with_examples_updated_at ON task_with_examples")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("DROP TABLE IF EXISTS memo_entries")
    op.execute("DROP INDEX IF EXISTS uq_prompt_list_user_title_when_prompt_null")
    op.execute("DROP TABLE IF EXISTS prompt_list_entries")
    op.execute("DROP TABLE IF EXISTS prompts")
    op.execute("DROP TABLE IF EXISTS task_with_examples")
    op.execute("DROP TABLE IF EXISTS shared_chat_rooms")
    op.execute("DROP TABLE IF EXISTS chat_history")
    op.execute("DROP TABLE IF EXISTS chat_rooms")
    op.execute("DROP TABLE IF EXISTS user_passkeys")
    op.execute("DROP INDEX IF EXISTS uq_users_provider_identity")
    op.execute("DROP TABLE IF EXISTS users")
