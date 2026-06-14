"""Add user_passkeys table for WebAuthn credentials.

Revision ID: 20260321_02
Revises: 20260321_01
Create Date: 2026-03-21 15:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260321_02"
down_revision: Union[str, Sequence[str], None] = "20260321_01"
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
    [JP] WebAuthn クレデンシャル用の user_passkeys テーブルとインデックスを作成します。
    [EN] Create the user_passkeys table and its index for WebAuthn credentials.
    """
    # [JP] users テーブルが存在しない場合は何も行わない
    # [EN] Do nothing if users table does not exist
    if "users" not in _existing_tables():
        return

    # [JP] user_passkeys テーブルの作成
    # [EN] Create user_passkeys table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_passkeys (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            credential_id VARCHAR(255) NOT NULL UNIQUE,
            public_key TEXT NOT NULL,
            sign_count BIGINT NOT NULL DEFAULT 0,
            aaguid VARCHAR(64) NULL,
            credential_device_type VARCHAR(32) NULL,
            credential_backed_up BOOLEAN NOT NULL DEFAULT FALSE,
            label VARCHAR(255) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP NULL,
            CONSTRAINT fk_user_passkeys_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
        """
    )
    # [JP] ユーザーIDと作成日時のインデックス作成
    # [EN] Create index on user_id and created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_passkeys_user_created_at
            ON user_passkeys (user_id, created_at DESC)
        """
    )


def downgrade() -> None:
    """
    [JP] user_passkeys テーブルとインデックスを削除します。
    [EN] Drop the user_passkeys table and its index.
    """
    # [JP] インデックスの削除
    # [EN] Drop the index
    op.execute("DROP INDEX IF EXISTS idx_user_passkeys_user_created_at")
    # [JP] テーブルの削除
    # [EN] Drop the table
    op.execute("DROP TABLE IF EXISTS user_passkeys")
