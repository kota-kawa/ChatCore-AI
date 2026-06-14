"""Add message-branching columns to chat_history and chat_rooms.

Turns the previously flat chat_history list into a tree:
- chat_history.parent_id points to the message this one replies to / branches from.
- chat_history.active_child_id points to the currently-selected child (branch tip walk).
- chat_rooms.active_root_id points to the active first message of the room.

Existing rooms are backfilled as a single linear branch so old conversations keep
rendering exactly as before (every message has version_count == 1).

Revision ID: 20260520_01
Revises: 20260518_01
Create Date: 2026-05-20 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260520_01"
down_revision: Union[str, Sequence[str], None] = "20260518_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 日本語: upgrade のスキーマ更新処理を担当します。
# English: Handle upgrading schema for upgrade.
def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_history
            ADD COLUMN IF NOT EXISTS parent_id INTEGER,
            ADD COLUMN IF NOT EXISTS active_child_id INTEGER
        """
    )
    op.execute(
        """
        ALTER TABLE chat_rooms
            ADD COLUMN IF NOT EXISTS active_root_id INTEGER
        """
    )

    # Self-referential FK so deleting a parent cascades to its whole subtree.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_chat_history_parent'
                  AND conrelid = 'chat_history'::regclass
            ) THEN
                ALTER TABLE chat_history
                    ADD CONSTRAINT fk_chat_history_parent
                    FOREIGN KEY (parent_id)
                    REFERENCES chat_history(id)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_history_room_parent
            ON chat_history (chat_room_id, parent_id)
        """
    )

    # Backfill existing flat history into a single linear branch per room.
    # parent_id = previous message id (by id order), active_child_id = next message id.
    op.execute(
        """
        WITH ordered AS (
            SELECT id,
                   LAG(id) OVER (PARTITION BY chat_room_id ORDER BY id) AS prev_id,
                   LEAD(id) OVER (PARTITION BY chat_room_id ORDER BY id) AS next_id
              FROM chat_history
        )
        UPDATE chat_history ch
           SET parent_id = ordered.prev_id,
               active_child_id = ordered.next_id
          FROM ordered
         WHERE ch.id = ordered.id
           AND ch.parent_id IS NULL
           AND ch.active_child_id IS NULL
        """
    )

    op.execute(
        """
        UPDATE chat_rooms cr
           SET active_root_id = sub.min_id
          FROM (
                SELECT chat_room_id, MIN(id) AS min_id
                  FROM chat_history
                 GROUP BY chat_room_id
               ) sub
         WHERE cr.id = sub.chat_room_id
           AND cr.active_root_id IS NULL
        """
    )


# 日本語: downgrade のスキーマ差し戻し処理を担当します。
# English: Handle downgrading schema for downgrade.
def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_rooms
            DROP COLUMN IF EXISTS active_root_id
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_chat_history_room_parent")
    op.execute(
        """
        ALTER TABLE chat_history
            DROP CONSTRAINT IF EXISTS fk_chat_history_parent
        """
    )
    op.execute(
        """
        ALTER TABLE chat_history
            DROP COLUMN IF EXISTS active_child_id,
            DROP COLUMN IF EXISTS parent_id
        """
    )
