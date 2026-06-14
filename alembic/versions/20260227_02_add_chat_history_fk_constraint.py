"""Add FK constraint from chat_history to chat_rooms.

Revision ID: 20260227_02
Revises: 20260227_01
Create Date: 2026-02-27 07:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260227_02"
down_revision: Union[str, Sequence[str], None] = "20260227_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    """
    [JP] 現在データベース内に存在するテーブル名のセットを返します。
    [EN] Return a set of table names existing in the database.
    """
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    """
    [JP] chat_history から chat_rooms への外部キー制約を追加し、不整合なデータをクリーンアップします。
    [EN] Add FK constraint from chat_history to chat_rooms and clean up inconsistent data.
    """
    tables = _existing_tables()
    # [JP] テーブルが存在しない場合は何も行わない
    # [EN] Do nothing if tables do not exist
    if "chat_history" not in tables or "chat_rooms" not in tables:
        return

    # [JP] 外部キー追加前に不整合データを除去して制約付与を可能にする。
    # [EN] Remove inconsistent data before adding the foreign key to make constraint enforcement possible.
    op.execute("DELETE FROM chat_history WHERE chat_room_id IS NULL")
    op.execute(
        """
        DELETE FROM chat_history ch
        WHERE NOT EXISTS (
            SELECT 1
            FROM chat_rooms cr
            WHERE cr.id = ch.chat_room_id
        )
        """
    )
    # [JP] chat_room_id カラムに NOT NULL 制約を設定
    # [EN] Set NOT NULL constraint on chat_room_id column
    op.execute(
        """
        ALTER TABLE chat_history
            ALTER COLUMN chat_room_id SET NOT NULL
        """
    )
    # [JP] 外国キー制約 (fk_chat_history_room) が存在しない場合のみ追加
    # [EN] Add foreign key constraint (fk_chat_history_room) only if it does not exist
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_chat_history_room'
                  AND conrelid = 'chat_history'::regclass
            ) THEN
                ALTER TABLE chat_history
                    ADD CONSTRAINT fk_chat_history_room
                    FOREIGN KEY (chat_room_id)
                    REFERENCES chat_rooms(id)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """
    [JP] chat_history から chat_rooms への外部キー制約と NOT NULL 制約を削除します。
    [EN] Remove FK constraint and NOT NULL constraint from chat_history table.
    """
    tables = _existing_tables()
    # [JP] chat_history テーブルが存在しない場合は何も行わない
    # [EN] Do nothing if chat_history table does not exist
    if "chat_history" not in tables:
        return

    # [JP] 外国キー制約 (fk_chat_history_room) の削除
    # [EN] Drop foreign key constraint (fk_chat_history_room)
    op.execute(
        """
        ALTER TABLE chat_history
            DROP CONSTRAINT IF EXISTS fk_chat_history_room
        """
    )
    # [JP] chat_room_id カラムから NOT NULL 制約を解除
    # [EN] Drop NOT NULL constraint on chat_room_id column
    op.execute(
        """
        ALTER TABLE chat_history
            ALTER COLUMN chat_room_id DROP NOT NULL
        """
    )
