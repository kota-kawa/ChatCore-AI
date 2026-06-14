"""Expand user profile columns from VARCHAR(255) to TEXT.

Revision ID: 20260502_01
Revises: 20260501_01
Create Date: 2026-05-02 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260502_01"
down_revision: Union[str, Sequence[str], None] = "20260501_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 日本語: upgrade のスキーマ更新処理を担当します。
# English: Handle upgrading schema for upgrade.
def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ALTER COLUMN avatar_url TYPE TEXT,
            ALTER COLUMN username   TYPE TEXT
        """
    )


# 日本語: downgrade のスキーマ差し戻し処理を担当します。
# English: Handle downgrading schema for downgrade.
def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ALTER COLUMN avatar_url TYPE VARCHAR(255),
            ALTER COLUMN username   TYPE VARCHAR(255)
        """
    )
