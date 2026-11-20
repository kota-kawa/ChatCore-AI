"""Add the per-user setting that turns the memory summary in chat answers on or off.

Revision ID: 20261120_04
Revises: 20261120_03
Create Date: 2026-11-20

`memory_use_enabled` decides whether the owner's saved memory is put into the chat context on every turn
(ADR 0025). It is separate from `context_auto_extract_enabled`, which decides whether memory is saved from
conversations. It starts on, for new and existing users alike, so the column is added with DEFAULT TRUE and no row is
rewritten (a constant default is metadata only).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261120_04"
down_revision: str | Sequence[str] | None = "20261120_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 追加のみ（expand）。旧バージョンのコードはこの列を知らず、users への INSERT では既定値が入るので、適用中に旧色が動いても壊れない。
    # ALTER TABLE は表全体の排他ロックを取る。users は認証のたびに読まれるため、長いトランザクションの後ろで待つと
    # ログインや全リクエストの認証が後ろに並ぶ。待ち時間に上限を付け、取れなければ失敗させて再実行できるようにする。
    # 同じトランザクションで流れる後続の revision に上限を持ち越さないよう、最後に戻す。
    # Expand only. An older code color does not know the column, and its INSERTs into users get the default, so it keeps
    # working while this runs. ALTER TABLE takes an exclusive lock on the table. users is read on every authenticated
    # request, so waiting behind a long transaction would queue them all behind it: the wait is bounded and the revision
    # fails and can be re-run. The limit is reset at the end so it does not carry into later revisions in the same transaction.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS memory_use_enabled BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("SET LOCAL lock_timeout TO DEFAULT")


def downgrade() -> None:
    raise RuntimeError(
        "20261120_04 is intentionally irreversible: dropping this column would discard every "
        "user's memory use preference."
    )
