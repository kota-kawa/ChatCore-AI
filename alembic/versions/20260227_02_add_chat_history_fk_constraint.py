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
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    tables = _existing_tables()
    if "chat_history" not in tables or "chat_rooms" not in tables:
        return

    # 外部キー追加前に不整合データを除去して制約付与を可能にする。
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
    op.execute(
        """
        ALTER TABLE chat_history
            ALTER COLUMN chat_room_id SET NOT NULL
        """
    )
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
    tables = _existing_tables()
    if "chat_history" not in tables:
        return

    op.execute(
        """
        ALTER TABLE chat_history
            DROP CONSTRAINT IF EXISTS fk_chat_history_room
        """
    )
    op.execute(
        """
        ALTER TABLE chat_history
            ALTER COLUMN chat_room_id DROP NOT NULL
        """
    )
