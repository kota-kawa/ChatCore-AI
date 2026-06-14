"""Add Google auth metadata columns to users.

Revision ID: 20260318_01
Revises: 20260227_02
Create Date: 2026-03-18 12:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260318_01"
down_revision: Union[str, Sequence[str], None] = "20260227_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 日本語: existing tables に関する処理の入口です。
# English: Entry point for logic related to existing tables.
def _existing_tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


# 日本語: upgrade のスキーマ更新処理を担当します。
# English: Handle upgrading schema for upgrade.
def upgrade() -> None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if "users" not in _existing_tables():
        return

    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(32)
        """
    )
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS provider_user_id VARCHAR(255)
        """
    )
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS provider_email VARCHAR(255)
        """
    )
    op.execute(
        """
        UPDATE users
           SET auth_provider = 'email'
         WHERE auth_provider IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE users
            ALTER COLUMN auth_provider SET DEFAULT 'email'
        """
    )
    op.execute(
        """
        ALTER TABLE users
            ALTER COLUMN auth_provider SET NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_provider_identity
            ON users (auth_provider, provider_user_id)
            WHERE provider_user_id IS NOT NULL
        """
    )


# 日本語: downgrade のスキーマ差し戻し処理を担当します。
# English: Handle downgrading schema for downgrade.
def downgrade() -> None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if "users" not in _existing_tables():
        return

    op.execute("DROP INDEX IF EXISTS uq_users_provider_identity")
    op.execute(
        """
        ALTER TABLE users
            DROP COLUMN IF EXISTS provider_email
        """
    )
    op.execute(
        """
        ALTER TABLE users
            DROP COLUMN IF EXISTS provider_user_id
        """
    )
    op.execute(
        """
        ALTER TABLE users
            DROP COLUMN IF EXISTS auth_provider
        """
    )
