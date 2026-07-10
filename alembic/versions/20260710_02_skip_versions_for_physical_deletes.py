"""Skip version-history triggers for physical deletes.

Revision ID: 20260710_02
Revises: 20260710_01
Create Date: 2026-07-10
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260710_02"
down_revision: Union[str, Sequence[str], None] = "20260710_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_version_trigger(table_name: str, trigger_name: str, function_name: str) -> None:
    """Record version history for mutations that retain their parent record."""
    op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")
    op.execute(
        f"""
        CREATE TRIGGER {trigger_name}
        AFTER INSERT OR UPDATE ON {table_name}
        FOR EACH ROW
        EXECUTE FUNCTION {function_name}();
        """
    )


def upgrade() -> None:
    """Avoid FK violations when account deletion removes tasks and prompts."""
    _replace_version_trigger(
        "task_with_examples",
        "trg_task_versions_record",
        "record_task_version",
    )
    _replace_version_trigger(
        "prompts",
        "trg_prompt_versions_record",
        "record_prompt_version",
    )


def downgrade() -> None:
    """Restore delete-event version history triggers."""
    op.execute("DROP TRIGGER IF EXISTS trg_task_versions_record ON task_with_examples")
    op.execute(
        """
        CREATE TRIGGER trg_task_versions_record
        AFTER INSERT OR UPDATE OR DELETE ON task_with_examples
        FOR EACH ROW
        EXECUTE FUNCTION record_task_version();
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_prompt_versions_record ON prompts")
    op.execute(
        """
        CREATE TRIGGER trg_prompt_versions_record
        AFTER INSERT OR UPDATE OR DELETE ON prompts
        FOR EACH ROW
        EXECUTE FUNCTION record_prompt_version();
        """
    )
