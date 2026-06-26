"""Add web_search_context column to chat_history.

Persists the raw web search results (titles, snippets, page-text excerpts)
attached to an assistant message so that later turns can reference prior
searches (e.g. "tell me more about the 3rd result"). The column is server-side
only and is never exposed to the frontend or shared-chat payloads.

Revision ID: 20260626_01
Revises: 20260621_01
Create Date: 2026-06-26 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260626_01"
down_revision: Union[str, Sequence[str], None] = "20260621_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'web_search_context' column (JSONB) to store serialized web search results per message
    # メッセージごとのWeb検索結果（直列化済み）を保存するため、chat_history に 'web_search_context' カラム (JSONB) を追加する
    op.execute(
        """
        ALTER TABLE chat_history
            ADD COLUMN IF NOT EXISTS web_search_context JSONB
        """
    )


def downgrade() -> None:
    # Remove 'web_search_context' column from 'chat_history' table
    # chat_history テーブルから 'web_search_context' カラムを削除する
    op.execute(
        """
        ALTER TABLE chat_history
            DROP COLUMN IF EXISTS web_search_context
        """
    )
