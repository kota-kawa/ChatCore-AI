"""Add shared memo entries table.

Revision ID: 20260322_07
Revises: 20260322_06
Create Date: 2026-03-22 18:10:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260322_07"
down_revision: Union[str, Sequence[str], None] = "20260322_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    [JP] 共有メモ機能用の shared_memo_entries テーブルとインデックスを作成します。
    [EN] Create the shared_memo_entries table and its index for shared memo feature.
    """
    # [JP] shared_memo_entries テーブルの作成
    # [EN] Create shared_memo_entries table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shared_memo_entries (
            id BIGSERIAL PRIMARY KEY,
            memo_entry_id BIGINT NOT NULL UNIQUE,
            share_token VARCHAR(128) NOT NULL UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_shared_memo_entries_memo
                FOREIGN KEY (memo_entry_id)
                REFERENCES memo_entries(id)
                ON DELETE CASCADE
        )
        """
    )
    # [JP] シェアトークンと作成日付に関するインデックス作成
    # [EN] Create index on share_token and created_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_shared_memo_entries_token_created_at
            ON shared_memo_entries (share_token, created_at DESC)
        """
    )


def downgrade() -> None:
    """
    [JP] shared_memo_entries テーブルとインデックスを削除します。
    [EN] Drop the shared_memo_entries table and its index.
    """
    # [JP] インデックスの削除
    # [EN] Drop the index
    op.execute("DROP INDEX IF EXISTS idx_shared_memo_entries_token_created_at")
    # [JP] テーブルの削除
    # [EN] Drop the table
    op.execute("DROP TABLE IF EXISTS shared_memo_entries")
