"""Keep where and when each memory fact was said, as one row per mention.

Revision ID: 20261120_01
Revises: 20261119_01
Create Date: 2026-11-20

Extraction used to check a quote of the user's own words against the message (after NFKC, whitespace and case
normalization, so not necessarily character-identical) and then throw it away, so a
fact only knew its `source_ref` string. `context_fact_sources` keeps one row per mention: the
quote, the user message it came from, the room, and when it was observed. How often and how
recently a fact was mentioned is derived from these rows, so no counter column is added to
context_facts. There is no backfill: facts saved before this revision never had a quote.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261120_01"
down_revision: str | Sequence[str] | None = "20261119_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 追加のみ（expand）。新しい表で既存の表と行は触らないため、旧バージョンのコードが同時に動いても壊れない
    # （旧コードは出典行を書かないだけ）。表を作る同じ revision 内で索引も作るので、他のセッションからは見えず
    # 書き込みを止めない。
    # Expand only: a new table, no existing table or row is touched, so an older code color keeps working
    # (it just writes no source rows). The indexes are created in the same revision as the table, so no other
    # session can see them and nothing is blocked.
    #
    # chat_room_id は chat_rooms.id（VARCHAR(255)）、user_message_id は chat_history.id（INTEGER）に型を揃える。
    # 部屋と事実を消せば出典も消える（CASCADE）。発話だけが消えた場合は行を残して NULL にする（SET NULL）。
    # chat_room_id matches chat_rooms.id (VARCHAR(255)) and user_message_id matches chat_history.id (INTEGER).
    # Deleting the room or the fact removes its sources (CASCADE); if only the message is deleted the row stays
    # with NULL (SET NULL).
    op.create_table(
        "context_fact_sources",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("fact_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chat_room_id", sa.String(length=255), nullable=False),
        sa.Column("user_message_id", sa.Integer(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=False),
        # timestamptz: 新しく作る表の近年の流儀（承認カード・デモコード・使用量）に合わせた。context_facts の日時は
        # タイムゾーンなしなので、比較するクエリはセッションの TimeZone で暗黙変換される（Python 側では naive と aware を混ぜない）。
        # timestamptz follows the recent convention for newly created tables (approvals, demo codes, usage). context_facts
        # datetimes are naive, so queries comparing them rely on the session TimeZone for the implicit cast (never mix
        # naive and aware values in Python).
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["fact_id"], ["context_facts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_room_id"], ["chat_rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["chat_history.id"], ondelete="SET NULL"),
        sa.CheckConstraint("char_length(evidence) BETWEEN 1 AND 1000", name="ck_context_fact_sources_evidence"),
    )
    # 事実ごとの新しい順の一覧と、古い出典の刈り込み。
    # Newest-first listing per fact, and pruning the oldest sources.
    op.create_index(
        "idx_context_fact_sources_fact_observed",
        "context_fact_sources",
        ["fact_id", sa.text("observed_at DESC"), sa.text("id DESC")],
    )
    # 部屋の削除（chat_rooms からの CASCADE）で全表走査にならないようにする。user_id は users からの CASCADE 用。
    # Keep the room delete cascade (from chat_rooms) and the account delete cascade (from users) off a table scan.
    op.create_index("idx_context_fact_sources_room", "context_fact_sources", ["chat_room_id"])
    op.create_index("idx_context_fact_sources_user", "context_fact_sources", ["user_id"])
    # 同じ発話から同じ事実への二重登録を防ぐ（一意）。発話が消えて NULL になった行は対象外。
    # Makes one message record at most one source per fact (unique); rows whose message is gone (NULL) are excluded.
    op.create_index(
        "uq_context_fact_sources_fact_message",
        "context_fact_sources",
        ["fact_id", "user_message_id"],
        unique=True,
        postgresql_where=sa.text("user_message_id IS NOT NULL"),
    )
    # 発話の削除（SET NULL）は user_message_id だけで行を探すので、fact_id が先頭の一意索引では支えられない。
    # The message-delete SET NULL finds rows by user_message_id alone, which the unique index (fact_id first) cannot serve.
    op.create_index(
        "idx_context_fact_sources_message",
        "context_fact_sources",
        ["user_message_id"],
        postgresql_where=sa.text("user_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    # 出典行は失われる（旧スキーマには持ち場所がない）。事実そのものには影響しない。実行前に論理バックアップを取ること。
    # The source rows are lost (the old schema has nowhere to keep them); the facts themselves are untouched.
    # Take a logical backup before running this.
    op.drop_table("context_fact_sources")
