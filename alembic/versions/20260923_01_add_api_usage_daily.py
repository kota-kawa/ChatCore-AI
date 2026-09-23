"""Record daily API usage and cost per billing subject.

Revision ID: 20260923_01
Revises: 20260919_01
Create Date: 2026-09-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260923_01"
down_revision: Union[str, Sequence[str], None] = "20260919_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Expand only: a new table that no previous Blue/Green color reads or writes.
    # 追加のみ: 旧バージョンが読み書きしない新しいテーブルを作るだけです。
    #
    # One row per (subject, day, resource) accumulates by upsert, so the table grows with
    # active subjects per day rather than with requests.  subject_key is deliberately not a
    # foreign key: usage from a deleted account must keep counting toward the monthly total.
    # 1行は (計上先, 日付, リソース) ごとの合計で、リクエスト数ではなく日ごとの利用者数に比例して
    # 増えます。subject_key を外部キーにしないのは、退会したアカウントの使用量も月間の合計に
    # 残す必要があるためです。
    op.create_table(
        "api_usage_daily",
        sa.Column("subject_key", sa.String(length=80), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("resource", sa.String(length=100), nullable=False),
        sa.Column("cost_nano_usd", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("cached_input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("request_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("subject_key", "usage_date", "resource"),
        sa.CheckConstraint(
            "cost_nano_usd >= 0 AND input_tokens >= 0 AND cached_input_tokens >= 0 "
            "AND output_tokens >= 0 AND request_count >= 0",
            name="ck_api_usage_daily_non_negative",
        ),
    )
    # The monthly total sums every subject over a date range, which the primary key
    # (leading with subject_key) cannot serve.
    # 月間の合計は全計上先を日付範囲で合計するため、subject_key から始まる主キーでは引けません。
    op.create_index(
        "idx_api_usage_daily_usage_date",
        "api_usage_daily",
        ["usage_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_api_usage_daily_usage_date", table_name="api_usage_daily", if_exists=True)
    op.drop_table("api_usage_daily")
