"""Move the shipped email and reply tasks onto the copy-card fence.

Revision ID: 20260809_01
Revises: 20260730_01
Create Date: 2026-08-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260809_01"
down_revision: Union[str, Sequence[str], None] = "20260730_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPDATED_FIELDS = (
    "prompt_template",
    "response_rules",
    "output_skeleton",
    "output_examples",
)

# 共有タスク（user_id IS NULL）は日本語カタログからシードされ、英語版は読み出し時に
# frontend/data/default_tasks.en.json から当てられる。よって DB を直す必要があるのは
# 日本語の本文だけで、英語側は JSON の更新だけで反映される。
# シードは既存キーを飛ばす挿入専用なので、配布済みの DB では ```text のまま残る。
# まだ配布時の本文と完全一致している行だけを書き換え、編集された行には触れない。
# Shared rows (user_id IS NULL) are seeded from the Japanese catalog, and the English
# wording is applied at read time from frontend/data/default_tasks.en.json, so only the
# Japanese text needs a database fix. Seeding is insert-only and skips existing keys, so
# a database that already has these rows would keep the ```text fence. Only rows whose
# wording still matches the shipped text exactly are rewritten; edited rows are left alone.
_TASK_TEXT_UPDATES: tuple[dict[str, object], ...] = tuple(
    [
        {
            "system_task_key": "email_writing",
            "previous": {
                "prompt_template": "状況や作業環境をもとに、相手と目的に合ったメール案を作成してください。件名と本文を明確に分け、Markdownで整理してください。本文はそのまま送れる完成文としてコードブロックで示してください。",
                "response_rules": "- 相手との関係性と目的を最初に整理する\n- 情報が不足している場合は、決め打ちせず不足点を短く確認する\n- 丁寧すぎる冗長表現は避け、自然で実務的な文面にする\n- 本文はコピペしやすいよう、説明と分けてコードブロックで示す",
                "output_skeleton": "## 件名\n- 件名案\n\n## 本文\n```text\n宛名\n\n導入\n\n要件\n\n結び\n```\n\n## 補足\n- 必要なら調整ポイント",
                "output_examples": "## 件名\n- 4/25（金）新機能説明会のご案内\n\n## 本文\n```text\n開発チーム各位\n\nお疲れさまです。4月25日（金）15:00より、新機能説明会を実施します。\n\n当日は機能概要、想定ユースケース、リリースまでのスケジュールを共有します。所要時間は30分程度です。\n\n参加が難しい場合は、後日録画を共有します。\n\nよろしくお願いします。\n```\n\n## 補足\n- 社内向けの簡潔な案内文"
            },
            "updated": {
                "prompt_template": "状況や作業環境をもとに、相手と目的に合ったメール案を作成してください。件名と本文を明確に分け、Markdownで整理してください。本文はそのまま送れる完成文として ```chatcore-copy ブロックで示してください。",
                "response_rules": "- 相手との関係性と目的を最初に整理する\n- 情報が不足している場合は、決め打ちせず不足点を短く確認する\n- 丁寧すぎる冗長表現は避け、自然で実務的な文面にする\n- 本文はコピペしやすいよう、説明と分けて ```chatcore-copy ブロックで示す",
                "output_skeleton": "## 件名\n- 件名案\n\n## 本文\n```chatcore-copy\n宛名\n\n導入\n\n要件\n\n結び\n```\n\n## 補足\n- 必要なら調整ポイント",
                "output_examples": "## 件名\n- 4/25（金）新機能説明会のご案内\n\n## 本文\n```chatcore-copy\n開発チーム各位\n\nお疲れさまです。4月25日（金）15:00より、新機能説明会を実施します。\n\n当日は機能概要、想定ユースケース、リリースまでのスケジュールを共有します。所要時間は30分程度です。\n\n参加が難しい場合は、後日録画を共有します。\n\nよろしくお願いします。\n```\n\n## 補足\n- 社内向けの簡潔な案内文"
            }
        },
        {
            "system_task_key": "reply_writing",
            "previous": {
                "prompt_template": "受け取ったメッセージに対して、相手との関係性と状況に合う自然な返信文を複数案考えてください。必要なら丁寧さの違いも出してください。各返信案はそのまま送れる完成文としてコードブロックで示してください。",
                "response_rules": "- 返信文はそのまま送れる自然さを優先する\n- 丁寧さや温度感の違いが分かるようにする\n- 返信文は説明と分けてコードブロックで示す\n- 補足では使い分けの目安を短く示す",
                "output_skeleton": "## 返信案\n### 丁寧め\n```text\n返信文\n```\n\n### 標準\n```text\n返信文\n```\n\n### カジュアル\n```text\n返信文\n```\n\n## 使い分け\n- 向いている場面",
                "output_examples": "## 返信案\n### 丁寧め\n```text\nご連絡ありがとうございます。\n\n承知しました。本日の打ち合わせは30分後ろ倒しで問題ございません。\n\nそれでは、開始時刻を改めてお待ちしております。よろしくお願いいたします。\n```\n\n### 標準\n```text\nご連絡ありがとうございます。30分後ろ倒し、承知しました。\n\n開始時刻になりましたら、よろしくお願いします。\n```\n\n## 使い分け\n- 取引先には丁寧め、普段やり取りの多い相手には標準案が使いやすい"
            },
            "updated": {
                "prompt_template": "受け取ったメッセージに対して、相手との関係性と状況に合う自然な返信文を複数案考えてください。必要なら丁寧さの違いも出してください。各返信案はそのまま送れる完成文として ```chatcore-copy ブロックで示してください。",
                "response_rules": "- 返信文はそのまま送れる自然さを優先する\n- 丁寧さや温度感の違いが分かるようにする\n- 返信文は説明と分けて、案ごとに ```chatcore-copy ブロックで示す\n- 補足では使い分けの目安を短く示す",
                "output_skeleton": "## 返信案\n### 丁寧め\n```chatcore-copy\n返信文\n```\n\n### 標準\n```chatcore-copy\n返信文\n```\n\n### カジュアル\n```chatcore-copy\n返信文\n```\n\n## 使い分け\n- 向いている場面",
                "output_examples": "## 返信案\n### 丁寧め\n```chatcore-copy\nご連絡ありがとうございます。\n\n承知しました。本日の打ち合わせは30分後ろ倒しで問題ございません。\n\nそれでは、開始時刻を改めてお待ちしております。よろしくお願いいたします。\n```\n\n### 標準\n```chatcore-copy\nご連絡ありがとうございます。30分後ろ倒し、承知しました。\n\n開始時刻になりましたら、よろしくお願いします。\n```\n\n## 使い分け\n- 取引先には丁寧め、普段やり取りの多い相手には標準案が使いやすい"
            }
        }
    ]
)


def _rewrite(previous_key: str, next_key: str) -> None:
    bind = op.get_bind()
    for update in _TASK_TEXT_UPDATES:
        previous = update[previous_key]
        following = update[next_key]
        bind.execute(
            sa.text(
                """
                UPDATE task_with_examples
                   SET prompt_template = :prompt_template,
                       response_rules = :response_rules,
                       output_skeleton = :output_skeleton,
                       output_examples = :output_examples
                 WHERE user_id IS NULL
                   AND system_task_key = :system_task_key
                   AND prompt_template = :previous_prompt_template
                   AND response_rules = :previous_response_rules
                   AND output_skeleton = :previous_output_skeleton
                   AND output_examples = :previous_output_examples
                """
            ),
            {
                "system_task_key": update["system_task_key"],
                **{field: following[field] for field in _UPDATED_FIELDS},
                **{f"previous_{field}": previous[field] for field in _UPDATED_FIELDS},
            },
        )


def upgrade() -> None:
    _rewrite("previous", "updated")


def downgrade() -> None:
    _rewrite("updated", "previous")
