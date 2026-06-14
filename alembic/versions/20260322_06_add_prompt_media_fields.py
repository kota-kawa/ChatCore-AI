"""Add prompt type and reference image fields to prompts.

Revision ID: 20260322_06
Revises: 20260322_05
Create Date: 2026-03-22 16:40:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260322_06"
down_revision: Union[str, Sequence[str], None] = "20260322_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    [JP] prompts テーブルに prompt_type と reference_image_url カラムを追加し、初期値を設定します。
    [EN] Add prompt_type and reference_image_url columns to prompts table and initialize values.
    """
    # [JP] prompt_type カラムの追加 (テキスト・マルチメディアの種別指定用)
    # [EN] Add prompt_type column (for specifying text vs multimedia prompt type)
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS prompt_type VARCHAR(20) NOT NULL DEFAULT 'text'
        """
    )
    # [JP] reference_image_url カラムの追加 (参考画像URL用)
    # [EN] Add reference_image_url column (for reference image URLs)
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS reference_image_url VARCHAR(255) NULL DEFAULT NULL
        """
    )
    # [JP] 既存レコードの空値・NULL値をデフォルト値の 'text' に更新
    # [EN] Update empty or NULL values in prompt_type to 'text' for existing records
    op.execute(
        """
        UPDATE prompts
           SET prompt_type = 'text'
         WHERE prompt_type IS NULL OR prompt_type = ''
        """
    )


def downgrade() -> None:
    """
    [JP] prompts テーブルから reference_image_url と prompt_type カラムを削除します。
    [EN] Drop reference_image_url and prompt_type columns from prompts table.
    """
    # [JP] reference_image_url カラムの削除
    # [EN] Drop reference_image_url column
    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS reference_image_url
        """
    )
    # [JP] prompt_type カラムの削除
    # [EN] Drop prompt_type column
    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS prompt_type
        """
    )
