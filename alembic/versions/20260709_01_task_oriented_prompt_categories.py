"""Move prompt categories from Japanese display labels to stable task-oriented keys.

Revision ID: 20260709_01
Revises: 20260626_01
Create Date: 2026-07-09 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260709_01"
down_revision: Union[str, Sequence[str], None] = "20260626_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 旧カテゴリ (日本語ラベル) から新しい安定キーへの対応。
# services/prompt_categories.py の LEGACY_CATEGORY_ALIASES と一致させること。
# Legacy Japanese category -> stable key. Keep in sync with LEGACY_CATEGORY_ALIASES.
_LEGACY_TO_KEY: dict[str, str] = {
    "恋愛": "daily_life",
    "旅行": "daily_life",
    "グルメ": "daily_life",
    "勉強": "learning",
    "趣味": "hobby",
    "スポーツ": "hobby",
    "音楽": "hobby",
    "仕事": "business",
    "その他": "other",
    "未選択": "",
}

# 新カテゴリの正準キー一覧 (既にキー化済みの行を再変換しないための判定に使う)。
# Canonical keys, used to leave already-migrated rows untouched.
_CANONICAL_KEYS: tuple[str, ...] = (
    "writing",
    "coding",
    "business",
    "learning",
    "research",
    "ideation",
    "creative",
    "language",
    "daily_life",
    "hobby",
    "other",
)


def _existing_tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def _build_case_expression(column: str) -> str:
    """旧値 -> 新キーの CASE 式を組み立てる。未知の非空値は 'other' に寄せる。"""
    whens = "\n                 ".join(
        f"WHEN {column} = '{legacy}' THEN '{key}'" for legacy, key in _LEGACY_TO_KEY.items()
    )
    canonical_list = ", ".join(f"'{key}'" for key in _CANONICAL_KEYS)
    return f"""
            CASE
                 WHEN {column} IS NULL THEN ''
                 WHEN TRIM({column}) = '' THEN ''
                 WHEN {column} IN ({canonical_list}) THEN {column}
                 {whens}
                 ELSE 'other'
            END
    """


def upgrade() -> None:
    """
    [JP] カテゴリを「話題」ベースの日本語ラベルから、タスク指向の安定キーへ移行する。
         旧値は legacy_category 列へ退避し、将来のタグ機能の初期値として再利用できるようにする。
         LIKE 検索用の trgm インデックスは等値照合には不要なため、btree インデックスへ置き換える。
    [EN] Migrate categories from Japanese topic labels to stable task-oriented keys.
         The original value is preserved in legacy_category so a future tagging feature can
         reuse it. The trgm index (built for LIKE) is replaced by a btree index for equality.
    """
    tables = _existing_tables()
    if "prompts" not in tables:
        return

    # 旧カテゴリ値を退避する列を追加 (情報を失わないため)。
    # Preserve the original category value so no information is lost.
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS legacy_category VARCHAR(50) NOT NULL DEFAULT ''
        """
    )
    op.execute("UPDATE prompts SET legacy_category = COALESCE(category, '')")

    # 旧値 -> 新キーへ変換。
    # Convert legacy values into canonical keys.
    op.execute(f"UPDATE prompts SET category = {_build_case_expression('category')}")

    # prompt_list_entries はカテゴリの非正規化コピーを持つため同じ変換を適用する。
    # prompt_list_entries carries a denormalized copy of the category; convert it the same way.
    if "prompt_list_entries" in tables:
        op.execute(
            f"UPDATE prompt_list_entries SET category = {_build_case_expression('category')}"
        )

    # カテゴリは部分一致ではなく等値で照合するようになったためインデックスを張り替える。
    # Categories are now matched by equality, not LIKE, so swap the index type.
    op.execute("DROP INDEX IF EXISTS idx_prompts_public_category_trgm")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_public_category
            ON prompts (category)
            WHERE is_public = TRUE
        """
    )


def downgrade() -> None:
    """
    [JP] 退避しておいた legacy_category から旧カテゴリ値を復元し、trgm インデックスを戻す。
    [EN] Restore the original category values from legacy_category and bring back the trgm index.
    """
    tables = _existing_tables()
    if "prompts" not in tables:
        return

    # 非正規化コピーを先に復元する (prompts の退避列を落とす前に参照する必要がある)。
    # Restore the denormalized copy first; it reads the preserved column before it is dropped.
    if "prompt_list_entries" in tables:
        op.execute(
            """
            UPDATE prompt_list_entries AS ple
               SET category = p.legacy_category
              FROM prompts AS p
             WHERE ple.prompt_id = p.id
               AND p.legacy_category <> ''
            """
        )

    # 退避列から旧値を復元する (退避が空の行は変更しない)。
    # Restore original values from the preserved column, leaving rows without a backup alone.
    op.execute(
        """
        UPDATE prompts
           SET category = legacy_category
         WHERE legacy_category <> ''
        """
    )
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS legacy_category")

    op.execute("DROP INDEX IF EXISTS idx_prompts_public_category")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prompts_public_category_trgm
            ON prompts USING gin (category gin_trgm_ops)
            WHERE is_public = TRUE
        """
    )
