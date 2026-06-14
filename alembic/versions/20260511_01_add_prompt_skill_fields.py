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
    if "prompts" not in _existing_tables():
        return

    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS skill_markdown TEXT NOT NULL DEFAULT ''
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS skill_python_script TEXT NOT NULL DEFAULT ''
        """
    )
    op.execute(
        """
        UPDATE prompts
           SET skill_markdown = COALESCE(skill_markdown, ''),
               skill_python_script = COALESCE(skill_python_script, '')
        """
    )


# 日本語: downgrade のスキーマ差し戻し処理を担当します。
# English: Handle downgrading schema for downgrade.
def downgrade() -> None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if "prompts" not in _existing_tables():
        return

    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS skill_python_script
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        DROP COLUMN IF EXISTS skill_markdown
        """
    )
