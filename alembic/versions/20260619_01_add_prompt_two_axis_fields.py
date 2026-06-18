"""Replace single prompt_type with two-axis model (content_format + media_type)
plus generic attributes/attachments JSONB columns.

Revision ID: 20260619_01
Revises: 20260618_02
Create Date: 2026-06-19 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260619_01"
down_revision: Union[str, Sequence[str], None] = "20260618_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    """
    [JP] prompts を「2軸モデル」へ移行する。content_format / media_type 列と、型固有の
         attributes / 汎用 attachments の JSONB 列を追加し、旧 prompt_type・reference_image_url・
         skill_markdown・skill_python_script からバックフィルしてから旧列を削除する。
    [EN] Migrate prompts to the two-axis model: add content_format/media_type plus
         attributes/attachments JSONB, backfill from the legacy columns, then drop them.
    """
    if "prompts" not in _existing_tables():
        return

    # 新カラム追加
    # Add new columns.
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS content_format VARCHAR(20) NOT NULL DEFAULT 'prompt'
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS media_type VARCHAR(20) NOT NULL DEFAULT 'text'
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS attributes JSONB NOT NULL DEFAULT '{}'::jsonb
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb
        """
    )

    # 旧 prompt_type -> 2軸へバックフィル
    # Backfill the two axes from legacy prompt_type.
    op.execute(
        """
        UPDATE prompts
           SET content_format = CASE WHEN prompt_type = 'skill' THEN 'skill' ELSE 'prompt' END,
               media_type     = CASE WHEN prompt_type = 'image' THEN 'image' ELSE 'text' END
        """
    )

    # skill_markdown / skill_python_script -> attributes へ移動 (skill行のみ)
    # Move skill text columns into attributes for skill rows.
    op.execute(
        """
        UPDATE prompts
           SET attributes = jsonb_build_object(
                 'skill_markdown', COALESCE(skill_markdown, ''),
                 'skill_python_script', COALESCE(skill_python_script, '')
               )
         WHERE prompt_type = 'skill'
        """
    )

    # reference_image_url -> attachments 配列へ移動
    # Move the reference image URL into the generic attachments array.
    op.execute(
        """
        UPDATE prompts
           SET attachments = jsonb_build_array(
                 jsonb_build_object(
                   'url', reference_image_url,
                   'role', 'reference',
                   'media_type', CASE
                     WHEN lower(reference_image_url) LIKE '%.png'  THEN 'image/png'
                     WHEN lower(reference_image_url) LIKE '%.jpg'  THEN 'image/jpeg'
                     WHEN lower(reference_image_url) LIKE '%.jpeg' THEN 'image/jpeg'
                     WHEN lower(reference_image_url) LIKE '%.webp' THEN 'image/webp'
                     WHEN lower(reference_image_url) LIKE '%.gif'  THEN 'image/gif'
                     ELSE 'image/*'
                   END
                 )
               )
         WHERE reference_image_url IS NOT NULL AND reference_image_url <> ''
        """
    )

    # 旧カラム削除
    # Drop legacy columns.
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS prompt_type")
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS reference_image_url")
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS skill_markdown")
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS skill_python_script")


def downgrade() -> None:
    """
    [JP] 2軸モデルから旧 prompt_type ベースの構造へ戻す。旧列を再作成し、新列から逆バックフィル
         してから新列を削除する。
    [EN] Revert to the legacy prompt_type structure: recreate the old columns, backfill them
         from the two-axis columns, then drop the new columns.
    """
    if "prompts" not in _existing_tables():
        return

    # 旧カラム再作成
    # Recreate legacy columns.
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS prompt_type VARCHAR(20) NOT NULL DEFAULT 'text'
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS reference_image_url VARCHAR(255) NULL DEFAULT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS skill_markdown TEXT NOT NULL DEFAULT ''
        """
    )
    op.execute(
        """
        ALTER TABLE prompts
        ADD COLUMN IF NOT EXISTS skill_python_script TEXT NOT NULL DEFAULT ''
        """
    )

    # 2軸 -> prompt_type へ逆変換
    # Derive legacy prompt_type from the two axes.
    op.execute(
        """
        UPDATE prompts
           SET prompt_type = CASE
                 WHEN content_format = 'skill' THEN 'skill'
                 WHEN media_type = 'image' THEN 'image'
                 ELSE 'text'
               END
        """
    )

    # attributes -> skill_* へ逆変換
    # Restore skill text columns from attributes.
    op.execute(
        """
        UPDATE prompts
           SET skill_markdown = COALESCE(attributes->>'skill_markdown', ''),
               skill_python_script = COALESCE(attributes->>'skill_python_script', '')
        """
    )

    # attachments -> reference_image_url へ逆変換 (先頭の添付URL)
    # Restore reference image URL from the first attachment.
    op.execute(
        """
        UPDATE prompts
           SET reference_image_url = attachments->0->>'url'
         WHERE jsonb_typeof(attachments) = 'array'
           AND jsonb_array_length(attachments) > 0
        """
    )

    # 新カラム削除
    # Drop the two-axis columns.
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS attachments")
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS attributes")
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS media_type")
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS content_format")
