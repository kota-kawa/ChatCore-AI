"""Add SKILL content fields to prompts.

Revision ID: 20260511_01
Revises: 20260502_01
Create Date: 2026-05-11 15:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260511_01"
down_revision: Union[str, Sequence[str], None] = "20260502_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    # Check if the prompts table exists.
    # promptsテーブルが存在することを確認します。
    if "prompts" not in _existing_tables():
        return

    # Add skill_markdown column to prompts table.
    # promptsテーブルにskill_markdown列を追加します。
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS skill_markdown TEXT NOT NULL DEFAULT ''
        """
    )
    # Add skill_python_script column to prompts table.
    # promptsテーブルにskill_python_script列を追加します。
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS skill_python_script TEXT NOT NULL DEFAULT ''
        """
    )
    # Ensure existing rows have non-null default values.
    # 既存の行に対して非nullのデフォルト値が設定されていることを保証します。
    op.execute(
        """
        UPDATE prompts
           SET skill_markdown = COALESCE(skill_markdown, ''),
               skill_python_script = COALESCE(skill_python_script, '')
        """
    )


def downgrade() -> None:
    # Check if the prompts table exists.
    # promptsテーブルが存在することを確認します。
    if "prompts" not in _existing_tables():
        return

    # Drop skill_python_script column from prompts table.
    # promptsテーブルからskill_python_script列を削除します。
    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS skill_python_script
        """
    )
    # Drop skill_markdown column from prompts table.
    # promptsテーブルからskill_markdown列を削除します。
    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS skill_markdown
        """
    )
