"""PostgreSQL integration coverage for guest ownership and version snapshots."""

from __future__ import annotations

import os
import unittest
from uuid import uuid4

from sqlalchemy import text

from services.db import dispose_engine, session_scope
from services.guest_prompt_service import (
    claim_guest_prompts_for_user,
    create_guest_shared_prompt,
)
from services.repositories.context_fact_repository import ContextFactRepository
from services.repositories.memo_embedding_repository import MemoEmbeddingRepository
from services.repositories.memo_repository import insert_memo, update_memo
from services.request_models import SharedPromptCreateRequest


@unittest.skipUnless(
    os.environ.get("DATABASE_URL"),
    "requires DATABASE_URL pointing at a PostgreSQL test database",
)
class DatabaseContractIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await dispose_engine()

    async def test_guest_prompt_and_task_history_preserve_nulls_and_full_rows(self) -> None:
        suffix = uuid4().hex
        guest_token = f"integration-guest-{suffix}"
        client_ip = "203.0.113.10"
        email = f"database-contract-{suffix}@example.test"
        task_name = f"integration-task-{suffix}"

        async with session_scope() as session:
            async with session.begin():
                user_id = int(
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO users (email, username)
                                VALUES (:email, :username)
                                RETURNING id
                                """
                            ),
                            {"email": email, "username": "統合テスト"},
                        )
                    ).scalar_one()
                )

                task_id = int(
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO task_with_examples (
                                    user_id, name, prompt_template, input_examples,
                                    output_examples, system_task_revision,
                                    is_system_task_customized
                                )
                                VALUES (
                                    NULL, :name, '本文', '入力例', '出力例', 7, TRUE
                                )
                                RETURNING id
                                """
                            ),
                            {"name": task_name},
                        )
                    ).scalar_one()
                )
                await session.execute(
                    text(
                        """
                        UPDATE task_with_examples
                           SET input_examples = NULL,
                               system_task_revision = 8
                         WHERE id = :task_id
                        """
                    ),
                    {"task_id": task_id},
                )
                task_versions = (
                    await session.execute(
                        text(
                            """
                            SELECT version_number, input_examples, snapshot
                              FROM task_versions
                             WHERE task_id = :task_id
                             ORDER BY version_number
                            """
                        ),
                        {"task_id": task_id},
                    )
                ).mappings().all()
                self.assertEqual([row["version_number"] for row in task_versions], [1, 2])
                self.assertEqual(task_versions[0]["snapshot"]["system_task_revision"], 7)
                self.assertIsNone(task_versions[1]["input_examples"])
                self.assertIsNone(task_versions[1]["snapshot"]["input_examples"])
                self.assertEqual(task_versions[1]["snapshot"]["system_task_revision"], 8)

                payload = SharedPromptCreateRequest(
                    title="統合テスト用ゲスト投稿",
                    category="",
                    content="ゲスト投稿の本文",
                    description="投稿の説明",
                    input_examples="入力例",
                    output_examples="出力例",
                    ai_model="test-model",
                )
                prompt_id = await create_guest_shared_prompt(
                    guest_token,
                    client_ip,
                    payload,
                    session=session,
                )
                first_version = (
                    await session.execute(
                        text(
                            """
                            SELECT user_id, snapshot
                              FROM prompt_versions
                             WHERE prompt_id = :prompt_id
                               AND version_number = 1
                            """
                        ),
                        {"prompt_id": prompt_id},
                    )
                ).mappings().one()
                self.assertIsNone(first_version["user_id"])
                self.assertIsNone(first_version["snapshot"]["user_id"])
                self.assertEqual(first_version["snapshot"]["description"], "投稿の説明")
                self.assertEqual(first_version["snapshot"]["attributes"], {})

                claimed = await claim_guest_prompts_for_user(
                    user_id,
                    guest_token,
                    session=session,
                )
                self.assertEqual(claimed, [prompt_id])

                await session.execute(
                    text(
                        """
                        UPDATE prompts
                           SET input_examples = NULL,
                               output_examples = NULL,
                               description = NULL,
                               attributes = '{}'::jsonb
                         WHERE id = :prompt_id
                        """
                    ),
                    {"prompt_id": prompt_id},
                )
                prompt_versions = (
                    await session.execute(
                        text(
                            """
                            SELECT version_number, user_id, input_examples, snapshot
                              FROM prompt_versions
                             WHERE prompt_id = :prompt_id
                             ORDER BY version_number
                            """
                        ),
                        {"prompt_id": prompt_id},
                    )
                ).mappings().all()
                self.assertEqual(
                    [row["version_number"] for row in prompt_versions],
                    [1, 2, 3],
                )
                self.assertEqual(prompt_versions[1]["user_id"], user_id)
                self.assertEqual(prompt_versions[1]["snapshot"]["user_id"], user_id)
                self.assertIsNone(prompt_versions[2]["input_examples"])
                self.assertIsNone(prompt_versions[2]["snapshot"]["input_examples"])
                self.assertIsNone(prompt_versions[2]["snapshot"]["description"])
                self.assertEqual(prompt_versions[2]["snapshot"]["attributes"], {})

                await session.execute(
                    text("DELETE FROM task_with_examples WHERE id = :task_id"),
                    {"task_id": task_id},
                )
                await session.execute(
                    text("DELETE FROM prompts WHERE id = :prompt_id"),
                    {"prompt_id": prompt_id},
                )
                await session.execute(
                    text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )

    async def test_embedding_status_follows_content_changes_and_successful_backfill(self) -> None:
        suffix = uuid4().hex
        email = f"embedding-contract-{suffix}@example.test"

        async with session_scope() as session:
            async with session.begin():
                user_id = int(
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO users (email, username)
                                VALUES (:email, :username)
                                RETURNING id
                                """
                            ),
                            {"email": email, "username": "Embedding 統合テスト"},
                        )
                    ).scalar_one()
                )

                memo_id = await insert_memo(
                    user_id,
                    "本文",
                    "タイトル",
                    None,
                    session=session,
                )
                self.assertIsNotNone(memo_id)
                pending_memo = await session.scalar(
                    text("SELECT embedding_status FROM memo_entries WHERE id = :id"),
                    {"id": memo_id},
                )
                self.assertEqual(pending_memo, "pending")

                await update_memo(
                    user_id,
                    int(memo_id),
                    title="更新タイトル",
                    ai_response=None,
                    collection_id=None,
                    clear_collection=False,
                    session=session,
                )
                await MemoEmbeddingRepository(session).store(
                    int(memo_id),
                    [0.0] * 768,
                )
                ready_memo = await session.scalar(
                    text("SELECT embedding_status FROM memo_entries WHERE id = :id"),
                    {"id": memo_id},
                )
                self.assertEqual(ready_memo, "ready")

                fact = await ContextFactRepository(session).create_fact(
                    user_id,
                    fact_type="preference",
                    title="エディタ",
                    content="vim",
                )
                fact_id = int(fact["id"])
                self.assertEqual(
                    await session.scalar(
                        text("SELECT embedding_status FROM context_facts WHERE id = :id"),
                        {"id": fact_id},
                    ),
                    "pending",
                )
                fact = await ContextFactRepository(session).update_fact(
                    user_id,
                    fact_id,
                    expected_revision=int(fact["revision"]),
                    content="neovim",
                )
                await ContextFactRepository(session).store_embedding(
                    fact_id,
                    [0.0] * 768,
                    expected_revision=int(fact["revision"]),
                )
                self.assertEqual(
                    await session.scalar(
                        text("SELECT embedding_status FROM context_facts WHERE id = :id"),
                        {"id": fact_id},
                    ),
                    "ready",
                )

                await session.execute(
                    text("DELETE FROM memo_entries WHERE id = :id"),
                    {"id": memo_id},
                )
                await session.execute(
                    text("DELETE FROM context_facts WHERE id = :id"),
                    {"id": fact_id},
                )
                await session.execute(
                    text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )


if __name__ == "__main__":
    unittest.main()
