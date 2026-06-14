"""Add task guidance fields for response rules and output skeleton.

Revision ID: 20260321_01
Revises: 20260318_01
Create Date: 2026-03-21 10:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260321_01"
down_revision: Union[str, Sequence[str], None] = "20260318_01"
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
    if "task_with_examples" not in _existing_tables():
        return

    op.execute(
        """
        ALTER TABLE task_with_examples
            ADD COLUMN IF NOT EXISTS response_rules TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE task_with_examples
            ADD COLUMN IF NOT EXISTS output_skeleton TEXT
        """
    )


# 日本語: downgrade のスキーマ差し戻し処理を担当します。
# English: Handle downgrading schema for downgrade.
def downgrade() -> None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if "task_with_examples" not in _existing_tables():
        return

    op.execute(
        """
        ALTER TABLE task_with_examples
            DROP COLUMN IF EXISTS output_skeleton
        """
    )
    op.execute(
        """
        ALTER TABLE task_with_examples
            DROP COLUMN IF EXISTS response_rules
        """
    )
