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


def _existing_tables() -> set[str]:
    """
    [JP] 現在データベース内に存在するテーブル名のセットを返します。
    [EN] Return a set of table names existing in the database.
    """
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    """
    [JP] task_with_examples テーブルに response_rules と output_skeleton カラムを追加します。
    [EN] Add response_rules and output_skeleton columns to task_with_examples table.
    """
    # [JP] task_with_examples テーブルが存在しない場合は何も行わない
    # [EN] Do nothing if task_with_examples table does not exist
    if "task_with_examples" not in _existing_tables():
        return

    # [JP] response_rules カラムの追加
    # [EN] Add response_rules column
    op.execute(
        """
        ALTER TABLE task_with_examples
            ADD COLUMN IF NOT EXISTS response_rules TEXT
        """
    )
    # [JP] output_skeleton カラムの追加
    # [EN] Add output_skeleton column
    op.execute(
        """
        ALTER TABLE task_with_examples
            ADD COLUMN IF NOT EXISTS output_skeleton TEXT
        """
    )


def downgrade() -> None:
    """
    [JP] task_with_examples テーブルから output_skeleton と response_rules カラムを削除します。
    [EN] Drop output_skeleton and response_rules columns from task_with_examples table.
    """
    # [JP] task_with_examples テーブルが存在しない場合は何も行わない
    # [EN] Do nothing if task_with_examples table does not exist
    if "task_with_examples" not in _existing_tables():
        return

    # [JP] output_skeleton カラムの削除
    # [EN] Drop output_skeleton column
    op.execute(
        """
        ALTER TABLE task_with_examples
            DROP COLUMN IF EXISTS output_skeleton
        """
    )
    # [JP] response_rules カラムの削除
    # [EN] Drop response_rules column
    op.execute(
        """
        ALTER TABLE task_with_examples
            DROP COLUMN IF EXISTS response_rules
        """
    )
