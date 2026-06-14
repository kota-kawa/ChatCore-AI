"""Add prompt likes table for persistent shared prompt likes.

Revision ID: 20260422_01
Revises: 20260420_02
Create Date: 2026-04-22 11:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260422_01"
down_revision: Union[str, Sequence[str], None] = "20260420_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    tables = _existing_tables()
    if "users" not in tables or "prompts" not in tables:
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_likes (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            prompt_id INT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_prompt_likes_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_prompt_likes_prompt
                FOREIGN KEY (prompt_id)
                REFERENCES prompts(id)
                ON DELETE CASCADE,
            CONSTRAINT uq_prompt_likes_user_prompt
                UNIQUE (user_id, prompt_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_likes_user_created_at
            ON prompt_likes (user_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_likes_prompt_created_at
            ON prompt_likes (prompt_id, created_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prompt_likes")
