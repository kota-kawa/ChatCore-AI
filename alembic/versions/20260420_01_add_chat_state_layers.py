"""Add chat room modes, summaries, and memory facts.

Revision ID: 20260420_01
Revises: 20260322_07
Create Date: 2026-04-20 12:00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260420_01"
down_revision: Union[str, Sequence[str], None] = "20260322_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_rooms
        ADD COLUMN IF NOT EXISTS mode VARCHAR(16) NOT NULL DEFAULT 'normal'
        """
    )
    op.execute(
        """
        ALTER TABLE chat_rooms
        DROP CONSTRAINT IF EXISTS chk_chat_rooms_mode
        """
    )
    op.execute(
        """
        ALTER TABLE chat_rooms
        ADD CONSTRAINT chk_chat_rooms_mode
        CHECK (mode IN ('normal', 'temporary'))
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_room_summaries (
            chat_room_id VARCHAR(255) PRIMARY KEY,
            summary TEXT NOT NULL,
            archived_message_count INT NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_chat_room_summaries_room
                FOREIGN KEY (chat_room_id)
                REFERENCES chat_rooms(id)
                ON DELETE CASCADE
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_facts (
            id SERIAL PRIMARY KEY,
            user_id INT NULL,
            chat_room_id VARCHAR(255) NULL,
            scope VARCHAR(16) NOT NULL DEFAULT 'room',
            fact TEXT NOT NULL,
            source_message_id INT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_memory_facts_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_memory_facts_room
                FOREIGN KEY (chat_room_id)
                REFERENCES chat_rooms(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_memory_facts_message
                FOREIGN KEY (source_message_id)
                REFERENCES chat_history(id)
                ON DELETE SET NULL,
            CONSTRAINT chk_memory_facts_scope
                CHECK (scope IN ('room', 'user'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_facts_room_updated_at
            ON memory_facts (chat_room_id, updated_at DESC)
            WHERE is_active = TRUE
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_facts_user_updated_at
            ON memory_facts (user_id, updated_at DESC)
            WHERE is_active = TRUE
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_facts_user_updated_at")
    op.execute("DROP INDEX IF EXISTS idx_memory_facts_room_updated_at")
    op.execute("DROP TABLE IF EXISTS memory_facts")
    op.execute("DROP TABLE IF EXISTS chat_room_summaries")
    op.execute("ALTER TABLE chat_rooms DROP CONSTRAINT IF EXISTS chk_chat_rooms_mode")
    op.execute("ALTER TABLE chat_rooms DROP COLUMN IF EXISTS mode")
