"""Add shared prompt comments and moderation reports.

Revision ID: 20260430_01
Revises: 20260422_01
Create Date: 2026-04-30 13:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260430_01"
down_revision: Union[str, Sequence[str], None] = "20260422_01"
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
        CREATE TABLE IF NOT EXISTS prompt_comments (
            id BIGSERIAL PRIMARY KEY,
            prompt_id INT NOT NULL,
            user_id INT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP NULL,
            hidden_by_reports_at TIMESTAMP NULL,
            hidden_reason VARCHAR(64) NULL,
            CONSTRAINT fk_prompt_comments_prompt
                FOREIGN KEY (prompt_id)
                REFERENCES prompts(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_prompt_comments_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_comments_prompt_visible_created_at
            ON prompt_comments (prompt_id, created_at DESC, id DESC)
            WHERE deleted_at IS NULL
              AND hidden_by_reports_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_comments_user_created_at
            ON prompt_comments (user_id, created_at DESC, id DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_comment_reports (
            id BIGSERIAL PRIMARY KEY,
            comment_id BIGINT NOT NULL,
            reporter_user_id INT NOT NULL,
            reason VARCHAR(32) NOT NULL,
            details TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_prompt_comment_reports_comment
                FOREIGN KEY (comment_id)
                REFERENCES prompt_comments(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_prompt_comment_reports_reporter
                FOREIGN KEY (reporter_user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,
            CONSTRAINT uq_prompt_comment_reports_comment_reporter
                UNIQUE (comment_id, reporter_user_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_comment_reports_comment_created_at
            ON prompt_comment_reports (comment_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_comment_reports_reporter_created_at
            ON prompt_comment_reports (reporter_user_id, created_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prompt_comment_reports")
    op.execute("DROP TABLE IF EXISTS prompt_comments")
