"""Store demo access codes that open a sample-filled, time-limited account per recipient.

Revision ID: 20261028_01
Revises: 20261005_01
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261028_01"
down_revision: str | Sequence[str] | None = "20261005_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 追加のみ（expand）。1行が応募先1件に配るコード。コード本体は保存せず SHA-256 の digest だけを持つ。
    # 初回利用でデモ用ユーザーを作って user_id に結び、その時点から expires_at までを利用期間とする。
    # 期限切れや停止でユーザーを削除しても行は残し（user_id は NULL になる）、管理画面で経緯を追える。
    # Expand only. One row is one code handed to one recipient. Only the code's SHA-256 digest is
    # stored. The first use creates the demo user, links it through user_id and starts the period
    # that ends at expires_at. Deleting the user on expiry or revocation keeps the row (user_id goes
    # NULL) so the admin screen still shows what happened.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS demo_access_codes (
            id SERIAL PRIMARY KEY,
            label VARCHAR(120) NOT NULL,
            code_digest CHAR(64) NOT NULL,
            user_id INTEGER,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            first_used_at TIMESTAMP WITH TIME ZONE,
            expires_at TIMESTAMP WITH TIME ZONE,
            revoked_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT uq_demo_access_codes_code_digest UNIQUE (code_digest),
            CONSTRAINT uq_demo_access_codes_user_id UNIQUE (user_id),
            CONSTRAINT fk_demo_access_codes_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    # 定期処理が期限切れのデモ用ユーザーだけを探すための索引。
    # Lets the periodic purge find only expired demo users.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_demo_access_codes_expires_at
            ON demo_access_codes (expires_at)
            WHERE user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "20261028_01 is intentionally irreversible: dropping demo_access_codes would orphan the demo "
        "users it links to, which the expiry purge could then never delete."
    )
