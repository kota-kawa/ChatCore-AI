"""Checks the permission and approval boundaries of chat Prompt and Skill tools."""

from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.chat_workspace_tools.private_overlap import PrivateTextTracker, extract_private_texts
from services.chat_workspace_tools.prompts import (
    PROMPTS_TOOL_SPECS,
    _execute_my_prompt_save,
    _execute_my_skill_save,
    _execute_public_prompt_edit,
    _execute_publish_prompt,
    _propose_my_prompt_save,
    _propose_my_skill_save,
    _propose_public_prompt_edit,
    _propose_publish_prompt,
    _read_my_prompt,
    _read_my_prompt_list,
    _read_my_skill,
    _read_my_skill_list,
)
from services.chat_workspace_tools.registry import WorkspaceToolError
from services.repositories.shared_content_repository import SharedContentRepository


class PromptWorkspaceToolTests(unittest.TestCase):
    @staticmethod
    def _task_edit_session(task: SimpleNamespace) -> SimpleNamespace:
        task_result = SimpleNamespace(scalar_one_or_none=lambda: task)
        return SimpleNamespace(
            execute=AsyncMock(side_effect=[None, task_result]),
            scalar=AsyncMock(return_value=None),
            flush=AsyncMock(),
        )

    def test_public_post_is_only_a_proposal_and_cannot_be_auto_approved(self):
        with patch("services.chat_workspace_tools.prompts.create_shared_prompt", new_callable=AsyncMock) as create:
            proposal = asyncio.run(_propose_publish_prompt(7, {"title": " Public ", "content": "Body"}))
        create.assert_not_awaited()
        self.assertEqual(proposal.preview["title"], "Public")
        self.assertEqual(proposal.target_ref, {})
        self.assertFalse(next(spec for spec in PROMPTS_TOOL_SPECS if spec.name == "publish_prompt").allows_always)

    def test_public_post_uses_the_web_channel_limit_before_writing(self):
        with (
            patch("services.chat_workspace_tools.prompts.consume_prompt_create_limits", return_value=(False, None, 15)) as limit,
            patch("services.chat_workspace_tools.prompts.create_shared_prompt", new_callable=AsyncMock) as create,
        ):
            with self.assertRaises(WorkspaceToolError) as raised:
                asyncio.run(
                    _execute_publish_prompt(None, 7, {"title": "Public", "content": "Body"}, {"_client_ip": "192.0.2.1"})
                )
        self.assertEqual(raised.exception.code, "prompt_rate_limited")
        limit.assert_called_once_with("192.0.2.1", 7)
        create.assert_not_awaited()

    def test_edit_saved_prompt_captures_and_checks_the_owned_revision(self):
        with patch("services.chat_workspace_tools.prompts.get_owned_task", new_callable=AsyncMock) as get_task:
            get_task.return_value = {"updated_at": "2026-09-28T00:00:00+00:00"}
            proposal = asyncio.run(
                _propose_my_prompt_save(7, {"task_id": 42, "title": "Revised", "prompt_content": "New body"})
            )
        get_task.assert_awaited_once_with(7, 42)
        self.assertEqual(proposal.target_ref, {"task_id": 42, "base_revision": "2026-09-28T00:00:00+00:00"})

        with patch("services.chat_workspace_tools.prompts.edit_task", new_callable=AsyncMock) as edit:
            asyncio.run(_execute_my_prompt_save(None, 7, proposal.arguments, proposal.target_ref))
        self.assertEqual(edit.await_args.args[:2], (7, 42))
        self.assertEqual(edit.await_args.kwargs["expected_updated_at"], "2026-09-28T00:00:00+00:00")

    def test_edit_saved_prompt_keeps_unspecified_optional_fields(self):
        with patch("services.chat_workspace_tools.prompts.get_owned_task", new_callable=AsyncMock) as get_task:
            get_task.return_value = {
                "updated_at": "2026-09-28T00:00:00+00:00",
                "response_rules": "Keep short",
                "output_skeleton": "Summary first",
                "input_examples": "Question",
                "output_examples": "Answer",
            }
            proposal = asyncio.run(
                _propose_my_prompt_save(7, {"task_id": 42, "title": "Revised", "prompt_content": "New body"})
            )
        self.assertEqual(proposal.preview["response_rules"], "Keep short")
        self.assertEqual(proposal.preview["output_skeleton"], "Summary first")
        with patch("services.chat_workspace_tools.prompts.edit_task", new_callable=AsyncMock) as edit:
            asyncio.run(_execute_my_prompt_save(None, 7, proposal.arguments, proposal.target_ref))
        self.assertEqual(edit.await_args.args[4:8], (None, None, None, None))

    def test_task_index_paginates_without_returning_large_private_bodies(self):
        tasks = [
            {
                "task_id": task_id,
                "name": f"Task {task_id}",
                "prompt_template": "private body " * 1_000,
                "updated_at": f"revision-{task_id}",
            }
            for task_id in range(25)
        ]
        with (
            patch("services.chat_workspace_tools.prompts.fetch_tasks", new_callable=AsyncMock, return_value=tasks),
            patch("services.chat_workspace_tools.prompts.get_current_locale", return_value="ja"),
        ):
            result = asyncio.run(_read_my_prompt_list(7, {"offset": 3, "limit": 2}, 4_000))

        self.assertEqual(result.payload["total"], 25)
        self.assertEqual(result.payload["offset"], 3)
        self.assertEqual(result.payload["next_offset"], 5)
        self.assertEqual([entry["task_id"] for entry in result.payload["prompts"]], [3, 4])
        self.assertNotIn("prompt_content", result.payload["prompts"][0])
        self.assertLessEqual(len(str(result.payload)), 4_000)

    def test_task_read_returns_requested_chunk_and_cursor(self):
        body = "0123456789" * 800
        with patch("services.chat_workspace_tools.prompts.get_owned_task", new_callable=AsyncMock) as get_task:
            get_task.return_value = {"task_id": 42, "name": "Long task", "prompt_template": body}
            result = asyncio.run(
                _read_my_prompt(7, {"task_id": 42, "start": 3_000, "length": 3_000}, 4_000)
            )

        get_task.assert_awaited_once_with(7, 42)
        self.assertEqual(result.payload["task"]["content"], body[3_000:6_000])
        self.assertEqual(result.payload["task"]["start"], 3_000)
        self.assertEqual(result.payload["task"]["end"], 6_000)
        self.assertEqual(result.payload["next_start"], 6_000)
        self.assertEqual(result.query, "task:42:prompt_content:3000")

    def test_skill_index_and_read_allow_finding_and_reading_long_instructions(self):
        skills = [
            {"id": skill_id, "name": f"Skill {skill_id}", "instructions": "private " * 1_000, "is_enabled": True}
            for skill_id in range(20)
        ]
        with patch(
            "services.chat_workspace_tools.prompts.list_personal_user_skills",
            new_callable=AsyncMock,
            return_value=skills,
        ):
            index = asyncio.run(_read_my_skill_list(7, {"offset": 18, "limit": 20}, 4_000))
        self.assertEqual(index.payload["total"], 20)
        self.assertEqual(index.payload["skills"][0]["skill_id"], 18)
        self.assertNotIn("instructions", index.payload["skills"][0])

        with patch("services.chat_workspace_tools.prompts.get_user_skill", new_callable=AsyncMock) as get_skill:
            get_skill.return_value = skills[9]
            result = asyncio.run(_read_my_skill(7, {"skill_id": 9, "start": 3_000, "length": 3_000}, 4_000))
        get_skill.assert_awaited_once_with(7, 9)
        self.assertEqual(result.payload["skill"]["content"], skills[9]["instructions"][3_000:6_000])
        self.assertEqual(result.payload["next_start"], 6_000)

    def test_task_edit_preview_names_the_existing_target_and_explicit_clears(self):
        with patch("services.chat_workspace_tools.prompts.get_owned_task", new_callable=AsyncMock) as get_task:
            get_task.return_value = {
                "name": "Existing task",
                "updated_at": "revision-1",
                "response_rules": "Old rules",
            }
            proposal = asyncio.run(
                _propose_my_prompt_save(
                    7,
                    {"task_id": 42, "title": "Renamed task", "prompt_content": "New body", "response_rules": ""},
                )
            )

        self.assertEqual(proposal.preview["current_title"], "Existing task")
        self.assertEqual(proposal.preview["clear_fields"], ["response_rules"])

    def test_edit_saved_prompt_allows_explicitly_clearing_an_optional_field(self):
        with patch("services.chat_workspace_tools.prompts.edit_task", new_callable=AsyncMock) as edit:
            asyncio.run(
                _execute_my_prompt_save(
                    None,
                    7,
                    {"task_id": 42, "title": "Revised", "prompt_content": "Body", "response_rules": ""},
                    {"task_id": 42, "base_revision": "v1"},
                )
            )
        self.assertEqual(edit.await_args.args[4], "")
        self.assertIsNone(edit.await_args.args[5])

    def test_create_saved_prompt_returns_the_new_task_id(self):
        with patch("services.chat_workspace_tools.prompts.add_task", new_callable=AsyncMock, return_value=42) as add:
            outcome = asyncio.run(
                _execute_my_prompt_save(
                    None,
                    7,
                    {"task_id": None, "title": "New task", "prompt_content": "Body"},
                    {},
                )
            )

        self.assertEqual(outcome.target_id, 42)
        add.assert_awaited_once()

    def test_approved_task_edit_uses_revision_and_refreshes_updated_at(self):
        revision = datetime(2026, 9, 28, tzinfo=UTC)
        task = SimpleNamespace(
            updated_at=revision,
            name="Original",
            prompt_template="Old body",
            response_rules="Keep this",
            output_skeleton=None,
            input_examples=None,
            output_examples=None,
            system_task_key=None,
            is_system_task_customized=False,
        )
        session = self._task_edit_session(task)

        asyncio.run(
            _execute_my_prompt_save(
                session,
                7,
                {"task_id": 42, "title": "Revised", "prompt_content": "New body"},
                {"task_id": 42, "base_revision": revision.isoformat()},
            )
        )

        self.assertEqual((task.name, task.prompt_template, task.response_rules), ("Revised", "New body", "Keep this"))
        self.assertEqual(str(task.updated_at), "CURRENT_TIMESTAMP")
        session.flush.assert_awaited_once()

    def test_approved_task_edit_rejects_a_stale_revision_before_writing(self):
        revision = datetime(2026, 9, 28, tzinfo=UTC)
        task = SimpleNamespace(
            updated_at=revision,
            name="Original",
            prompt_template="Old body",
            response_rules="Keep this",
            output_skeleton=None,
            input_examples=None,
            output_examples=None,
            system_task_key=None,
            is_system_task_customized=False,
        )
        session = self._task_edit_session(task)

        with self.assertRaises(WorkspaceToolError) as raised:
            asyncio.run(
                _execute_my_prompt_save(
                    session,
                    7,
                    {"task_id": 42, "title": "Revised", "prompt_content": "New body"},
                    {"task_id": 42, "base_revision": "stale"},
                )
            )

        self.assertEqual(raised.exception.code, "target_changed")
        self.assertEqual((task.name, task.prompt_template), ("Original", "Old body"))
        session.flush.assert_not_awaited()

    def test_public_prompt_edit_is_approval_only_and_uses_the_owned_revision(self):
        session = SimpleNamespace()

        @asynccontextmanager
        async def fake_session_scope():
            yield session

        with (
            patch("services.chat_workspace_tools.prompts.session_scope", fake_session_scope),
            patch.object(SharedContentRepository, "get_owned_public_text_prompt", new_callable=AsyncMock) as get_prompt,
        ):
            get_prompt.return_value = {"title": "Old", "content": "Old body", "updated_at": "v1"}
            proposal = asyncio.run(
                _propose_public_prompt_edit(7, {"prompt_id": 42, "title": "New", "content": "New body"})
            )
        get_prompt.assert_awaited_once_with(session, user_id=7, prompt_id=42)
        self.assertEqual(proposal.preview["before_content"], "Old body")
        self.assertEqual(proposal.target_ref, {"prompt_id": 42, "base_revision": "v1"})
        self.assertFalse(next(spec for spec in PROMPTS_TOOL_SPECS if spec.name == "public_prompt_edit").allows_always)

        with patch.object(SharedContentRepository, "update_owned_public_text_prompt", new_callable=AsyncMock) as update:
            outcome = asyncio.run(_execute_public_prompt_edit(session, 7, proposal.arguments, proposal.target_ref))
        update.assert_awaited_once_with(
            session, user_id=7, prompt_id=42, title="New", content="New body", expected_updated_at="v1"
        )
        self.assertEqual(outcome.target_id, 42)

    def test_public_prompt_edit_rejects_a_swapped_id(self):
        with patch.object(SharedContentRepository, "update_owned_public_text_prompt", new_callable=AsyncMock) as update:
            with self.assertRaises(WorkspaceToolError) as raised:
                asyncio.run(
                    _execute_public_prompt_edit(
                        None, 7, {"prompt_id": 99, "title": "New", "content": "Body"}, {"prompt_id": 42}
                    )
                )
        self.assertEqual(raised.exception.code, "target_changed")
        update.assert_not_awaited()

    def test_public_prompt_repository_scopes_owner_visibility_format_and_revision(self):
        session = SimpleNamespace(scalar=AsyncMock(), flush=AsyncMock())
        repository = SharedContentRepository()
        session.scalar.return_value = None
        with self.assertRaises(ResourceNotFoundError):
            asyncio.run(repository.get_owned_public_text_prompt(session, user_id=7, prompt_id=42))
        query = str(session.scalar.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
        for required in (
            "prompts.user_id = 7",
            "prompts.id = 42",
            "prompts.is_public IS true",
            "prompts.deleted_at IS NULL",
            "prompts.content_format = 'prompt'",
            "prompts.media_type = 'text'",
        ):
            self.assertIn(required, query)

        prompt = SimpleNamespace(
            id=42,
            title="Old",
            content="Old body",
            updated_at=datetime(2026, 9, 28, tzinfo=UTC),
            embedding_status="completed",
        )
        session.scalar.return_value = prompt
        with self.assertRaises(ApiServiceError) as raised:
            asyncio.run(
                repository.update_owned_public_text_prompt(
                    session, user_id=7, prompt_id=42, title="New", content="Body", expected_updated_at="stale"
                )
            )
        self.assertEqual(raised.exception.code, "target_changed")
        self.assertEqual(prompt.title, "Old")
        session.flush.assert_not_awaited()

        revision = datetime(2026, 9, 28, tzinfo=UTC).isoformat()
        asyncio.run(
            repository.update_owned_public_text_prompt(
                session, user_id=7, prompt_id=42, title="New", content="Body", expected_updated_at=revision
            )
        )
        self.assertEqual((prompt.title, prompt.content, prompt.embedding_status), ("New", "Body", "pending"))
        session.flush.assert_awaited_once()

    def test_edit_personal_skill_captures_and_checks_the_owned_revision(self):
        with patch("services.chat_workspace_tools.prompts.get_user_skill", new_callable=AsyncMock) as get_skill:
            get_skill.return_value = {"name": "Old", "updated_at": "2026-09-28T00:00:00+00:00"}
            proposal = asyncio.run(_propose_my_skill_save(7, {"skill_id": 9, "instructions": "New instructions"}))
        get_skill.assert_awaited_once_with(7, 9)
        self.assertEqual(proposal.target_ref, {"skill_id": 9, "base_revision": "2026-09-28T00:00:00+00:00"})
        self.assertEqual(proposal.preview["current_name"], "Old")

        with patch("services.chat_workspace_tools.prompts.update_user_skill", new_callable=AsyncMock) as update:
            update.return_value = {"name": "Old"}
            asyncio.run(_execute_my_skill_save(None, 7, proposal.arguments, proposal.target_ref))
        self.assertEqual(update.await_args.args[:2], (7, 9))
        self.assertEqual(update.await_args.kwargs["expected_updated_at"], "2026-09-28T00:00:00+00:00")

    def test_private_text_tracker_warns_only_for_long_verbatim_overlap(self):
        private = "Private meeting notes and customer details remain in this account only."
        tracker = PrivateTextTracker()
        for text in extract_private_texts({"prompts": [{"prompt_content": private}]}):
            tracker.add(text)
        self.assertEqual(tracker.find_overlaps(f"Public prefix. {private} Public suffix."), [private])
        self.assertEqual(tracker.find_overlaps("Private meeting notes"), [])

    def test_private_text_tracker_warns_for_overlap_across_adjacent_chunks(self):
        tracker = PrivateTextTracker()
        tracker.add_chunk("task:42:prompt_content", 0, "a" * 2_975 + "x" * 25)
        tracker.add_chunk("task:42:prompt_content", 3_000, "y" * 25 + "b" * 2_975)

        self.assertEqual(tracker.find_overlaps("x" * 25 + "y" * 25), ["x" * 25 + "y" * 25])

    def test_private_text_tracker_keeps_a_rolling_tail_for_short_chunks(self):
        tracker = PrivateTextTracker()
        private = "0123456789" * 5
        for start in range(0, len(private), 10):
            tracker.add_chunk("task:42:prompt_content", start, private[start : start + 10])

        self.assertEqual(tracker.find_overlaps(private), [private])

    def test_private_text_tracker_keeps_earlier_chunks_within_the_tracking_limit(self):
        tracker = PrivateTextTracker()
        private = "These internal launch plans are confidential and should never be posted publicly."
        first_chunk = private + "x" * (3_000 - len(private))
        tracker.add_chunk("task:42:prompt_content", 0, first_chunk)
        for index in range(1, 12):
            tracker.add_chunk("task:42:prompt_content", index * 3_000, "z" * 3_000)

        self.assertEqual(tracker.find_overlaps(private), [private])

    def test_private_text_tracker_does_not_join_non_adjacent_chunks(self):
        tracker = PrivateTextTracker()
        tracker.add_chunk("task:42:prompt_content", 0, "x" * 25)
        tracker.add_chunk("task:42:prompt_content", 26, "y" * 25)

        self.assertEqual(tracker.find_overlaps("x" * 25 + "y" * 25), [])

    def test_private_text_tracker_handles_long_repeated_content(self):
        tracker = PrivateTextTracker()
        tracker.add("a" * 20_000)
        self.assertEqual(tracker.find_overlaps("prefix" + "a" * 20_000), ["a" * 200 + "…"])


if __name__ == "__main__":
    unittest.main()
