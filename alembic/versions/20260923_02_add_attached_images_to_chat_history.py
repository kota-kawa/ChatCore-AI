"""Add attached image references to chat history.

Revision ID: 20260923_02
Revises: 20260923_01
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260923_02"
down_revision: Union[str, Sequence[str], None] = "20260923_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Expand only: a nullable column that the previous Blue/Green color neither reads nor writes.
    # It holds image ids and dimensions; the image bytes live in the private chat image storage.
    # 追加のみ: 旧バージョンが読み書きしない NULL 許容の列です。
    # 画像IDと寸法だけを持ち、画像本体は非公開のチャット画像保存先に置きます。
    op.execute(
        """
        ALTER TABLE chat_history
            ADD COLUMN IF NOT EXISTS attached_images JSONB
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_history
            DROP COLUMN IF EXISTS attached_images
        """
    )
