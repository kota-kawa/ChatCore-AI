-- Runtime-safe index additions for existing PostgreSQL environments.
-- All indexes use IF NOT EXISTS to avoid duplicate-object failures.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_chat_rooms_user_created_at
    ON chat_rooms (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_history_room_id_id
    ON chat_history (chat_room_id, id);

CREATE INDEX IF NOT EXISTS idx_task_with_examples_user_name
    ON task_with_examples (user_id, name);

CREATE INDEX IF NOT EXISTS idx_task_with_examples_user_order
    ON task_with_examples (user_id, display_order, id);

CREATE INDEX IF NOT EXISTS idx_task_with_examples_user_created_at
    ON task_with_examples (user_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_prompts_public_created_at
    ON prompts (is_public, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_prompts_user_created_at
    ON prompts (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_prompts_public_title_trgm
    ON prompts USING gin (title gin_trgm_ops)
    WHERE is_public = TRUE;

CREATE INDEX IF NOT EXISTS idx_prompts_public_content_trgm
    ON prompts USING gin (content gin_trgm_ops)
    WHERE is_public = TRUE;

CREATE INDEX IF NOT EXISTS idx_prompts_public_category_trgm
    ON prompts USING gin (category gin_trgm_ops)
    WHERE is_public = TRUE;

CREATE INDEX IF NOT EXISTS idx_prompts_public_author_trgm
    ON prompts USING gin (author gin_trgm_ops)
    WHERE is_public = TRUE;

CREATE INDEX IF NOT EXISTS idx_prompt_list_user_created_at
    ON prompt_list_entries (user_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_memo_entries_created_at
    ON memo_entries (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memo_entries_user_created_at
    ON memo_entries (user_id, created_at DESC);
