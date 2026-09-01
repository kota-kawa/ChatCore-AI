"""Track chat room activity for history ordering.

Revision ID: 20260901_01
Revises: 20260829_02
Create Date: 2026-09-01

# migration-review: approved-data-backfill
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260901_01"
down_revision: Union[str, Sequence[str], None] = "20260829_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_rooms",
        sa.Column(
            "last_activity_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.execute(
        """
        UPDATE chat_rooms AS room
           SET last_activity_at = COALESCE(
               (
                   SELECT MAX(history.timestamp)
                     FROM chat_history AS history
                    WHERE history.chat_room_id = room.id
               ),
               room.created_at,
               CURRENT_TIMESTAMP
           )
        """
    )
    op.create_index(
        "idx_chat_rooms_user_last_activity_id",
        "chat_rooms",
        ["user_id", sa.text("last_activity_at DESC"), sa.text("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_chat_rooms_user_last_activity_id", table_name="chat_rooms")
    op.drop_column("chat_rooms", "last_activity_at")
