"""Add ai_model column to prompts table.

Revision ID: 20260322_05
Revises: 20260322_04
Create Date: 2026-03-22 14:00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260322_05"
down_revision: Union[str, Sequence[str], None] = "20260322_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    [JP] prompts テーブルに ai_model カラムを追加します。
    [EN] Add ai_model column to prompts table.
    """
    # [JP] ai_model カラムの追加 (推奨されるAIモデル名の格納用)
    # [EN] Add ai_model column (for storing recommended AI model name)
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS ai_model VARCHAR(100) NULL DEFAULT NULL
        """
    )


def downgrade() -> None:
    """
    [JP] prompts テーブルから ai_model カラムを削除します。
    [EN] Drop ai_model column from prompts table.
    """
    # [JP] ai_model カラムの削除
    # [EN] Drop ai_model column
    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS ai_model
        """
    )
