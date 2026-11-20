"""Turn the memory automatic-extraction setting on by default and for every existing user.

Revision ID: 20261119_01
Revises: 20261028_01
Create Date: 2026-11-19

Extraction used to queue candidates for the owner's approval, so it was opt-in (default FALSE).
Extracted content is now saved directly as unconfirmed memory (ADR 0023), and the owner reviews,
edits, and disables it on the memory screen. The product decision is that the feature starts on, including for
users who had turned it off, so the existing rows are set to TRUE as well. The previous
per-user values are not kept anywhere, so a downgrade cannot restore them.

# migration-review: approved-data-backfill
Every user row is updated once; users has no updated_at trigger, so no other column moves.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261119_01"
down_revision: str | Sequence[str] | None = "20261028_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 初期値を TRUE にし、既存ユーザーも TRUE にする。旧バージョンのコードは列を読むだけなので、適用中に旧色が動いても壊れない
    # （旧コードで TRUE の利用者は、従来どおり承認待ち候補へ入る）。
    # Flip the column default and set existing users to TRUE. Older code only reads the column, so the old
    # color keeps working during the migration (it queues candidates for TRUE users, as before).
    op.execute("ALTER TABLE users ALTER COLUMN context_auto_extract_enabled SET DEFAULT TRUE")
    op.execute("UPDATE users SET context_auto_extract_enabled = TRUE WHERE context_auto_extract_enabled = FALSE")


def downgrade() -> None:
    # 初期値だけを FALSE に戻す。個別の設定値は復元できない（upgrade が全員を TRUE にしたため、元がオフだった人を区別できない）。
    # Only the default goes back to FALSE. Per-user values cannot be restored: the upgrade set everyone to TRUE,
    # so users who had it off are indistinguishable.
    op.execute("ALTER TABLE users ALTER COLUMN context_auto_extract_enabled SET DEFAULT FALSE")
