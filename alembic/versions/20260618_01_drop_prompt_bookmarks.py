"""Drop prompt bookmark list entries.

Revision ID: 20260618_01
Revises: 20260603_01
Create Date: 2026-06-18 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260618_01"
down_revision: Union[str, Sequence[str], None] = "20260603_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prompt_list_entries")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_list_entries (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            prompt_id INT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_prompt_list_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_prompt_list_prompt
                FOREIGN KEY (prompt_id)
                REFERENCES prompts(id)
                ON DELETE CASCADE,
            CONSTRAINT uq_prompt_list_user_prompt
                UNIQUE (user_id, prompt_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_list_user_created_at
            ON prompt_list_entries (user_id, created_at DESC, id DESC)
        """
    )
