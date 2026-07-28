"""Add stable provenance for localized system tasks.

Revision ID: 20260728_02
Revises: 20260728_01
Create Date: 2026-07-28
"""

from __future__ import annotations

import hashlib
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_02"
down_revision: Union[str, Sequence[str], None] = "20260728_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TASK_FIELDS = (
    "name",
    "prompt_template",
    "response_rules",
    "output_skeleton",
    "input_examples",
    "output_examples",
)

# Frozen fingerprints of the Japanese system tasks at migration creation time.
# A row is marked as a system task only when every editable field still matches,
# so user-customized copies are never reclassified or overwritten.
_SYSTEM_TASK_KEY_BY_FINGERPRINT = {
    "a0760faa2bf9e92270f3fa364b4705b9865ecd71eebcbdedc2590262299292d3": "information",
    "e37d251a279c2ab20bcf321f29cdf567cd52736d800cefc10cc4316331526ee5": "ideation",
    "9f5cedeb438eab517c03d2a9c7c424675108c4ca10a6cb6a149e798f3660e192": "problem_solving",
    "980ae39cf8995a7ab5469f637bebd2058efe31cec33ec401d5eb071fede5e7bf": "email_writing",
    "c777ab94288fdffa64af9192095f3d9884013e22ef309206c740c20e0f2809f0": "translation",
    "79e4fd482a9c92af41475c2fd5f9ed7628cf391140320b0ac1114b143292de79": "summarization",
    "8dead62027fd9281aeff8f451db08df0d99a187165cfec8e4827c43709412e64": "comparison",
    "1beef4874309a9f8e2308860f003a951ae60246dd21fab516f913497efb3980e": "question_answering",
    "c432dd781717aa8eb16793cbb9cb6b8c08a14c56581dca23864f6deb58272777": "proofreading",
    "5638b791f3cf26deb2e35bf733f34078b78e5e481893dbb3414889216f551467": "reply_writing",
    "b9f234c74819528eb95e433c4ac430e16bf9c316f2a3cc4cedc7c93fbe316971": "longform_writing",
    "98a888be1618527106c7784319be26b39d7dcb4c1ef97e0d1c530323ed33cfc2": "meeting_notes",
    "f6d90328e52f6d36373972d3ca523e7b69f452f5a7f87b810f8da7cabcd21e20": "personal_advice",
    "ae97c21691001efc5a47570ec9c61cc584e170150f84b1ce51aaeff4d8463c25": "travel_planning",
}


def _fingerprint(row: dict[str, object]) -> str:
    payload = json.dumps(
        [str(row.get(field) or "") for field in _TASK_FIELDS],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.add_column(
        "prompts",
        sa.Column("system_prompt_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "prompts",
        sa.Column("content_locale", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "idx_prompts_system_prompt_locale",
        "prompts",
        ["system_prompt_key", "content_locale"],
        unique=False,
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE prompts AS p
               SET system_prompt_key = CASE p.title
                       WHEN '会議の議事録を短時間で整理するテンプレート' THEN 'meeting_minutes'
                       WHEN '英語プレゼン練習用フィードバックプロンプト' THEN 'english_presentation_feedback'
                       WHEN '旅行プランを予算内で最適化するプロンプト' THEN 'budget_travel_planning'
                       WHEN '趣味ブログのネタ出しと構成案を作る' THEN 'hobby_blog_outline'
                       ELSE NULL
                   END,
                   content_locale = 'ja'
              FROM users AS u
             WHERE p.user_id = u.id
               AND u.email = 'sample-prompts@chat-core.local'
               AND p.deleted_at IS NULL
               AND p.title IN (
                   '会議の議事録を短時間で整理するテンプレート',
                   '英語プレゼン練習用フィードバックプロンプト',
                   '旅行プランを予算内で最適化するプロンプト',
                   '趣味ブログのネタ出しと構成案を作る'
               )
            """
        )
    )

    op.add_column(
        "task_with_examples",
        sa.Column("system_task_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "idx_task_with_examples_system_task_key",
        "task_with_examples",
        ["system_task_key"],
        unique=False,
    )

    rows = bind.execute(
        sa.text(
            """
            SELECT id, name, prompt_template, response_rules, output_skeleton,
                   input_examples, output_examples
              FROM task_with_examples
             WHERE deleted_at IS NULL
            """
        )
    ).mappings()
    for row in rows:
        system_task_key = _SYSTEM_TASK_KEY_BY_FINGERPRINT.get(_fingerprint(dict(row)))
        if system_task_key is None:
            continue
        bind.execute(
            sa.text(
                """
                UPDATE task_with_examples
                   SET system_task_key = :system_task_key
                 WHERE id = :task_id
                """
            ),
            {"system_task_key": system_task_key, "task_id": row["id"]},
        )


def downgrade() -> None:
    op.drop_index(
        "idx_task_with_examples_system_task_key",
        table_name="task_with_examples",
    )
    op.drop_column("task_with_examples", "system_task_key")
    op.drop_index("idx_prompts_system_prompt_locale", table_name="prompts")
    op.drop_column("prompts", "content_locale")
    op.drop_column("prompts", "system_prompt_key")
