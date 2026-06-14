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


def _existing_tables() -> set[str]:
    """
    [JP] 現在データベース内に存在するテーブル名のセットを返します。
    [EN] Return a set of table names existing in the database.
    """
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    """
    [JP] users テーブルに Google 認証関連のメタデータカラムを追加し、初期値を設定してインデックスを作成します。
    [EN] Add Google auth metadata columns to the users table, set default values, and create a unique index.
    """
    # [JP] users テーブルが存在しない場合は何も行わない
    # [EN] Do nothing if users table does not exist
    if "users" not in _existing_tables():
        return

    # [JP] auth_provider カラムの追加
    # [EN] Add auth_provider column
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(32)
        """
    )
    # [JP] provider_user_id カラムの追加
    # [EN] Add provider_user_id column
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS provider_user_id VARCHAR(255)
        """
    )
    # [JP] provider_email カラムの追加
    # [EN] Add provider_email column
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS provider_email VARCHAR(255)
        """
    )
    # [JP] 既存レコードの auth_provider が NULL のものを 'email' に更新
    # [EN] Update existing records' auth_provider to 'email' where it is NULL
    op.execute(
        """
        UPDATE users
           SET auth_provider = 'email'
         WHERE auth_provider IS NULL
        """
    )
    # [JP] auth_provider のデフォルト値を 'email' に設定
    # [EN] Set DEFAULT 'email' for auth_provider column
    op.execute(
        """
        ALTER TABLE users
            ALTER COLUMN auth_provider SET DEFAULT 'email'
        """
    )
    # [JP] auth_provider カラムに NOT NULL 制約を設定
    # [EN] Set NOT NULL constraint on auth_provider column
    op.execute(
        """
        ALTER TABLE users
            ALTER COLUMN auth_provider SET NOT NULL
        """
    )
    # [JP] プロバイダーごとの ID 重複を防ぐための部分ユニークインデックスの作成
    # [EN] Create unique partial index to prevent duplicate identities per auth provider
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_provider_identity
            ON users (auth_provider, provider_user_id)
            WHERE provider_user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """
    [JP] users テーブルから Google 認証関連のインデックスとカラムを削除します。
    [EN] Drop Google auth metadata index and columns from users table.
    """
    # [JP] users テーブルが存在しない場合は何も行わない
    # [EN] Do nothing if users table does not exist
    if "users" not in _existing_tables():
        return

    # [JP] ユニークインデックスの削除
    # [EN] Drop unique index
    op.execute("DROP INDEX IF EXISTS uq_users_provider_identity")
    # [JP] provider_email カラムの削除
    # [EN] Drop provider_email column
    op.execute(
        """
        ALTER TABLE users
            DROP COLUMN IF EXISTS provider_email
        """
    )
    # [JP] provider_user_id カラムの削除
    # [EN] Drop provider_user_id column
    op.execute(
        """
        ALTER TABLE users
            DROP COLUMN IF EXISTS provider_user_id
        """
    )
    # [JP] auth_provider カラムの削除
    # [EN] Drop auth_provider column
    op.execute(
        """
        ALTER TABLE users
            DROP COLUMN IF EXISTS auth_provider
        """
    )
