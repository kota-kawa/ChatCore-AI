"""Store chat write-tool approvals, "always approve" grants and the memo tools Skill preference.

Revision ID: 20260924_03
Revises: 20260924_02
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_03"
down_revision: Union[str, Sequence[str], None] = "20260924_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # チャットの書き込みツールは実行せずに承認待ちとして保存し、利用者が承認カードで決めてから
    # サーバーが実行する。1行が1枚のカード。arguments は提案時の引数、preview はカードに出す
    # 変更内容、target_ref は提案時の対象（メモの ID・版・共有中か）とターンの文脈を持つ。
    # assistant_message_id は回答を保存した時点で結び付くので、それまでは NULL になる。
    # Chat write tools do not run on the spot: each proposal is stored here as a pending
    # approval and the server runs it only after the user decides on the card. One row is one
    # card. arguments is the proposed input, preview the change shown on the card, and
    # target_ref the target as proposed (memo id, revision, whether it was shared) plus the
    # turn context. assistant_message_id is filled in when the reply is saved, so it starts NULL.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_tool_approvals (
            id UUID PRIMARY KEY,
            user_id INTEGER NOT NULL,
            chat_room_id VARCHAR(255) NOT NULL,
            assistant_message_id INTEGER,
            tool_name VARCHAR(64) NOT NULL,
            arguments JSONB NOT NULL,
            preview JSONB NOT NULL,
            target_ref JSONB,
            status VARCHAR(16) NOT NULL,
            decision VARCHAR(16),
            result JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            decided_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT fk_chat_tool_approvals_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            CONSTRAINT fk_chat_tool_approvals_room
                FOREIGN KEY (chat_room_id) REFERENCES chat_rooms(id) ON DELETE CASCADE,
            CONSTRAINT fk_chat_tool_approvals_message
                FOREIGN KEY (assistant_message_id) REFERENCES chat_history(id) ON DELETE CASCADE,
            CONSTRAINT ck_chat_tool_approvals_status
                CHECK (status IN (
                    'pending', 'succeeded', 'failed', 'denied', 'expired', 'superseded', 'cancelled'
                )),
            CONSTRAINT ck_chat_tool_approvals_decision
                CHECK (decision IS NULL OR decision IN ('once', 'always', 'auto', 'deny'))
        )
        """
    )
    # 新しい発言のたびに、そのルームの承認待ちだけを探して無効にする。
    # Every new message looks up only the room's pending approvals to supersede them.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_tool_approvals_room_pending
            ON chat_tool_approvals (chat_room_id)
            WHERE status = 'pending'
        """
    )
    # 回答メッセージの削除（ON DELETE CASCADE）が表を全走査しないための索引。
    # Keeps the ON DELETE CASCADE from a reply message from scanning the whole table.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_tool_approvals_message
            ON chat_tool_approvals (assistant_message_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_tool_approvals_user_created_at
            ON chat_tool_approvals (user_id, created_at DESC)
        """
    )

    # 「常に承認」を付与したツール。取り消しは行の削除で表す。
    # Tools the user granted "always approve"; revoking deletes the row.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_tool_auto_approvals (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            tool_name VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_approval_id UUID,
            CONSTRAINT fk_chat_tool_auto_approvals_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            CONSTRAINT fk_chat_tool_auto_approvals_source
                FOREIGN KEY (source_approval_id) REFERENCES chat_tool_approvals(id) ON DELETE SET NULL,
            CONSTRAINT uq_chat_tool_auto_approvals_user_tool UNIQUE (user_id, tool_name)
        )
        """
    )
    # 付与元の承認行の削除（ON DELETE SET NULL）が表を全走査しないための索引。
    # Keeps the ON DELETE SET NULL from the source approval from scanning the whole table.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_tool_auto_approvals_source
            ON chat_tool_auto_approvals (source_approval_id)
            WHERE source_approval_id IS NOT NULL
        """
    )

    # 追加のみ: 既定スキル「メモ」の ON/OFF。新規・既存ユーザーとも ON で始める。
    # Expand only: the on/off state of the built-in "Memo" Skill, on for new and existing users.
    op.add_column(
        "users",
        sa.Column(
            "memo_tools_skill_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "20260924_03 is intentionally irreversible: dropping these tables and the column would "
        "discard pending approvals, users' always-approve grants and their Memo Skill preference."
    )
