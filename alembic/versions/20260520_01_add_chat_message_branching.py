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


def upgrade() -> None:
    # 1. Add parent_id and active_child_id columns to chat_history to enable a tree structure for message branching
    # 1. メッセージの分岐（ツリー構造）を可能にするため、chat_history テーブルに parent_id と active_child_id カラムを追加する
    op.execute(
        """
        ALTER TABLE chat_history
            ADD COLUMN IF NOT EXISTS parent_id INTEGER,
            ADD COLUMN IF NOT EXISTS active_child_id INTEGER
        """
    )
    # 2. Add active_root_id column to chat_rooms to track the active starting message of the room
    # 2. チャットルームのアクティブな最初のメッセージを追跡するため、chat_rooms テーブルに active_root_id カラムを追加する
    op.execute(
        """
        ALTER TABLE chat_rooms
            ADD COLUMN IF NOT EXISTS active_root_id INTEGER
        """
    )

    # 3. Add a self-referential foreign key constraint to chat_history so that deleting a message cascades to its sub-branches
    # 3. メッセージが削除された際にそのサブブランチも連鎖的に削除されるよう、chat_history に自己参照の外部キー制約を追加する
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

    # 4. Create an index on (chat_room_id, parent_id) to optimize tree traversal and branch lookup
    # 4. ツリーの探索やブランチの検索を最適化するため、(chat_room_id, parent_id) に対するインデックスを作成する
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_history_room_parent
            ON chat_history (chat_room_id, parent_id)
        """
    )

    # 5. Backfill existing flat history into a single linear branch per room using window functions (LAG and LEAD)
    # 5. ウィンドウ関数 (LAG と LEAD) を使用して、既存のフラットな履歴をルームごとの単一の線形ブランチとしてバックフィルする
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

    # 6. Set active_root_id to the earliest message ID for existing chat rooms
    # 6. 既存のチャットルームに対して、最も古いメッセージIDを active_root_id に設定する
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


def downgrade() -> None:
    # 1. Remove active_root_id column from chat_rooms
    # 1. chat_rooms テーブルから active_root_id カラムを削除する
    op.execute(
        """
        ALTER TABLE chat_rooms
            DROP COLUMN IF EXISTS active_root_id
        """
    )
    # 2. Drop the composite index for message relationships
    # 2. メッセージ関係の複合インデックスを削除する
    op.execute("DROP INDEX IF EXISTS idx_chat_history_room_parent")
    # 3. Drop the self-referential foreign key constraint fk_chat_history_parent from chat_history
    # 3. chat_history から自己参照外部キー制約 fk_chat_history_parent を削除する
    op.execute(
        """
        ALTER TABLE chat_history
            DROP CONSTRAINT IF EXISTS fk_chat_history_parent
        """
    )
    # 4. Drop active_child_id and parent_id columns from chat_history
    # 4. chat_history テーブルから active_child_id と parent_id カラムを削除する
    op.execute(
        """
        ALTER TABLE chat_history
            DROP COLUMN IF EXISTS active_child_id,
            DROP COLUMN IF EXISTS parent_id
        """
    )
