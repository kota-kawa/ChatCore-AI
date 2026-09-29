"""Contracts for private profile settings tools and approval-time compare-and-set writes."""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi import Request
from pydantic import ValidationError

from blueprints.chat.tool_approvals import _sync_approved_profile_locale
from services.chat_agent_budget import AgentStepBudget
from services.chat_generation import _includes_external_evidence
from services.chat_generation_telemetry import ChatGenerationTelemetry
from services.chat_generation_turn import ChatTurnRunState
from services.chat_turn_state import TurnStateUpdateFilter
from services.chat_use_case import ChatPostUseCase
from services.chat_workspace_tools import build_workspace_toolbox
from services.chat_workspace_tools.profile import (
    PROFILE_BIO_READ_MAX_LENGTH,
    PROFILE_CONTEXT_READ_MAX_LENGTH,
    PROFILE_SETTINGS_READ_TOOL_NAME,
    PROFILE_SETTINGS_UPDATE_TOOL_NAME,
    ProfileSettingsUpdateArguments,
    _execute_profile_settings_update,
    _propose_profile_settings_update,
    _read_profile_settings,
)
from services.chat_workspace_tools.registry import WorkspaceToolError
from services.chat_workspace_tools.runner import WorkspaceToolRunner
from services.repositories.user_repository import UserRepository, profile_settings_fingerprint


def _profile(**overrides):
    profile = {
        "id": 7,
        "username": "Mika",
        "bio": "",
        "llm_profile_context": "",
        "preferred_locale": "ja",
    }
    profile.update(overrides)
    return profile


def _tool_call(name: str, **arguments):
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _generation_state():
    evidence_store = MagicMock()
    evidence_store.add_reference_payload.return_value = ()
    return ChatTurnRunState(
        chunks=[],
        telemetry=ChatGenerationTelemetry(),
        budget=AgentStepBudget(max_llm_turns=8, max_tool_calls=6),
        page_fetch_budget=MagicMock(),
        evidence_context_budget=MagicMock(),
        evidence_store=evidence_store,
        web_page_reader=MagicMock(),
        turn_state=MagicMock(),
        turn_base_messages=[],
        latest_user_message="",
        selected_web_search_images=[],
        continuation_state_filter=TurnStateUpdateFilter(),
    )


class ProfileSettingsArgumentTests(unittest.TestCase):
    def test_update_accepts_empty_strings_to_clear_bio_and_context(self):
        parsed = ProfileSettingsUpdateArguments.model_validate({"bio": "", "llm_profile_context": ""})

        self.assertEqual(parsed.model_dump(exclude_unset=True), {"bio": "", "llm_profile_context": ""})

    def test_update_requires_a_nonempty_display_name_and_at_least_one_field(self):
        for payload in ({}, {"display_name": "  "}, {"bio": None}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                ProfileSettingsUpdateArguments.model_validate(payload)

    def test_update_checks_locale_theme_and_profile_text_limits(self):
        with self.assertRaises(ValidationError):
            ProfileSettingsUpdateArguments.model_validate({"preferred_locale": "fr"})
        with self.assertRaises(ValidationError):
            ProfileSettingsUpdateArguments.model_validate({"theme": "system"})
        with self.assertRaises(ValidationError):
            ProfileSettingsUpdateArguments.model_validate({"llm_profile_context": "x" * 20_001})


class ProfileSettingsReadTests(unittest.TestCase):
    def test_read_excludes_email_and_avatar_and_omits_unrequested_theme(self):
        profile = _profile(
            bio="b" * 2_000,
            llm_profile_context="c" * 10_000,
            email="private@example.com",
            avatar_url="/private/avatar.png",
        )
        with patch("services.chat_workspace_tools.profile.get_chat_profile_settings", new=AsyncMock(return_value=profile)):
            result = asyncio.run(
                _read_profile_settings(
                    7,
                    {"include_bio": True, "include_llm_profile_context": True},
                    max_chars=4_000,
                )
            )

        payload = result.payload
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False)), 4_000)
        self.assertLessEqual(len(payload["llm_profile_context"]), PROFILE_CONTEXT_READ_MAX_LENGTH)
        self.assertGreater(payload["next_llm_profile_context_start"], 0)
        self.assertNotIn("theme", payload)
        self.assertNotIn("theme_note", payload)

    def test_read_can_return_the_current_browser_theme_only_when_requested(self):
        with patch(
            "services.chat_workspace_tools.profile.get_chat_profile_settings",
            new=AsyncMock(return_value=_profile()),
        ):
            payload = asyncio.run(
                _read_profile_settings(7, {"include_theme": True}, max_chars=4_000)
            ).payload

        self.assertEqual(payload["theme"], None)
        self.assertIn("unknown to the server", payload["theme_note"])
        self.assertIn("localStorage", payload["theme_note"])
        self.assertNotIn("email", payload)
        self.assertNotIn("avatar_url", payload)

    def test_read_omits_bio_and_personal_context_unless_requested(self):
        profile = _profile(bio="private bio", llm_profile_context="private context")
        with patch(
            "services.chat_workspace_tools.profile.get_chat_profile_settings",
            new=AsyncMock(return_value=profile),
        ):
            payload = asyncio.run(_read_profile_settings(7, {}, max_chars=4_000)).payload

        self.assertEqual(payload["display_name"], "Mika")
        self.assertNotIn("bio", payload)
        self.assertNotIn("llm_profile_context", payload)
        self.assertNotIn("private bio", json.dumps(payload))
        self.assertNotIn("private context", json.dumps(payload))

    def test_read_returns_contiguous_context_chunks(self):
        context = "a" * 100 + "b" * 100
        with patch(
            "services.chat_workspace_tools.profile.get_chat_profile_settings",
            new=AsyncMock(return_value=_profile(llm_profile_context=context)),
        ):
            first = asyncio.run(
                _read_profile_settings(
                    7,
                    {"include_llm_profile_context": True, "llm_profile_context_length": 100},
                    max_chars=4_000,
                )
            ).payload
            second = asyncio.run(
                _read_profile_settings(
                    7,
                    {
                        "include_llm_profile_context": True,
                        "llm_profile_context_start": first["next_llm_profile_context_start"],
                        "llm_profile_context_length": 100,
                    },
                    max_chars=4_000,
                )
            ).payload

        self.assertEqual(first["llm_profile_context"] + second["llm_profile_context"], context)

    def test_private_profile_reads_are_registered_as_own_evidence_and_overlap_text(self):
        private_bio = "private-bio-text-" + "y" * 70
        private_context = "private-profile-text-" + "x" * 70
        toolbox = build_workspace_toolbox(
            user_id=7,
            chat_room_id="room-7",
            memo_tools_enabled=False,
            prompt_tools_enabled=False,
            external_input_in_turn=False,
        )
        runner = WorkspaceToolRunner(toolbox, publish=lambda *_: None)
        state = _generation_state()

        with patch(
            "services.chat_workspace_tools.profile.get_chat_profile_settings",
            new=AsyncMock(
                return_value=_profile(bio=private_bio, llm_profile_context=private_context)
            ),
        ):
            runner.run(
                state,
                _tool_call(
                    PROFILE_SETTINGS_READ_TOOL_NAME,
                    include_bio=True,
                    include_llm_profile_context=True,
                    bio_length=45,
                    llm_profile_context_length=45,
                ),
            )
            runner.run(
                state,
                _tool_call(
                    PROFILE_SETTINGS_READ_TOOL_NAME,
                    include_bio=True,
                    include_llm_profile_context=True,
                    bio_start=45,
                    bio_length=PROFILE_BIO_READ_MAX_LENGTH,
                    llm_profile_context_start=45,
                    llm_profile_context_length=PROFILE_CONTEXT_READ_MAX_LENGTH,
                ),
            )

        _, kwargs = state.evidence_store.add_reference_payload.call_args
        self.assertEqual(kwargs["source_type"], "profile")
        self.assertEqual(runner._private_texts.find_overlaps(private_bio), [private_bio])
        self.assertEqual(runner._private_texts.find_overlaps(private_context), [private_context])
        self.assertFalse(_includes_external_evidence({"evidence": [{"source_type": "profile"}]}))

    def test_runner_returns_the_theme_preference_from_the_current_browser_on_read_request(self):
        toolbox = build_workspace_toolbox(
            user_id=7,
            chat_room_id="room-7",
            memo_tools_enabled=False,
            prompt_tools_enabled=False,
            external_input_in_turn=False,
            browser_theme_preference="dark",
        )
        runner = WorkspaceToolRunner(toolbox, publish=lambda *_: None)
        state = _generation_state()
        with patch(
            "services.chat_workspace_tools.profile.get_chat_profile_settings",
            new=AsyncMock(return_value=_profile()),
        ):
            result = runner.run(state, _tool_call(PROFILE_SETTINGS_READ_TOOL_NAME, include_theme=True))

        self.assertEqual(result["theme"], "dark")
        self.assertIn("supplied by this browser", result["theme_note"])


class ProfileToolAvailabilityTests(unittest.TestCase):
    def test_authenticated_normal_streaming_chat_gets_profile_tools_when_both_skills_are_off(self):
        use_case = object.__new__(ChatPostUseCase)
        use_case.deps = SimpleNamespace(generation=SimpleNamespace(is_streaming_model=Mock(return_value=True)))
        turn = SimpleNamespace(
            user_id=7,
            targets_normal_room=lambda: True,
            model="streaming-model",
            memo_tools_enabled=False,
            prompt_tools_enabled=False,
            chat_room_id="room-7",
            user_profile_prompt="Private context",
            theme_preference="dark",
            prepared_attached_files=[],
            prepared_attached_images=[],
            pasted_url_pages=(),
            use_shared_prompts=False,
            attachments_in_context=False,
        )

        toolbox = use_case._build_workspace_toolbox(turn)

        self.assertEqual(
            {definition["function"]["name"] for definition in toolbox.definitions()},
            {PROFILE_SETTINGS_READ_TOOL_NAME, PROFILE_SETTINGS_UPDATE_TOOL_NAME},
        )
        self.assertEqual(toolbox.llm_profile_context, "Private context")
        self.assertEqual(toolbox.browser_theme_preference, "dark")
        self.assertFalse(toolbox.external_input_in_turn)

        # 過去ターンの添付が文脈に戻るターンは、外部の内容を読んだターンとして扱う（issue #781）。
        # A turn whose context carries an earlier upload counts as reading external content (issue #781).
        turn.attachments_in_context = True
        self.assertTrue(use_case._build_workspace_toolbox(turn).external_input_in_turn)

    def test_guest_temporary_and_non_streaming_turns_do_not_get_profile_tools(self):
        use_case = object.__new__(ChatPostUseCase)
        streaming_model = Mock(return_value=True)
        use_case.deps = SimpleNamespace(generation=SimpleNamespace(is_streaming_model=streaming_model))
        turn = SimpleNamespace(
            user_id=None,
            targets_normal_room=lambda: False,
            model="streaming-model",
        )
        self.assertIsNone(use_case._build_workspace_toolbox(turn))
        streaming_model.assert_not_called()

        turn.user_id = 7
        self.assertIsNone(use_case._build_workspace_toolbox(turn))

        turn.targets_normal_room = lambda: True
        use_case.deps.generation.is_streaming_model = Mock(return_value=False)
        self.assertIsNone(use_case._build_workspace_toolbox(turn))


class ProfileSettingsProposalAndExecutionTests(unittest.TestCase):
    def test_proposal_contains_only_requested_values_and_hashes_the_base_state(self):
        current = _profile(llm_profile_context="stored private text")
        with patch(
            "services.chat_workspace_tools.profile.get_chat_profile_settings",
            new=AsyncMock(return_value=current),
        ):
            proposal = asyncio.run(
                _propose_profile_settings_update(
                    7,
                    {"display_name": "  Sora  ", "bio": "", "preferred_locale": "en", "theme": "dark"},
                )
            )

        self.assertEqual(proposal.arguments["display_name"], "Sora")
        self.assertEqual(
            proposal.preview,
            {
                "kind": PROFILE_SETTINGS_UPDATE_TOOL_NAME,
                "display_name": "Sora",
                "bio": "",
                "preferred_locale": "en",
                "theme": "dark",
            },
        )
        self.assertNotIn("stored private text", json.dumps(proposal.target_ref))
        self.assertEqual(
            proposal.target_ref["base_profile_fingerprint"],
            profile_settings_fingerprint(current),
        )

    def test_runner_saves_an_approval_card_without_executing_the_profile_write(self):
        toolbox = build_workspace_toolbox(
            user_id=7,
            chat_room_id="room-7",
            memo_tools_enabled=False,
            prompt_tools_enabled=False,
            external_input_in_turn=False,
        )
        runner = WorkspaceToolRunner(toolbox, publish=lambda *_: None)
        state = _generation_state()
        current = _profile()

        with (
            patch(
                "services.chat_workspace_tools.profile.get_chat_profile_settings",
                new=AsyncMock(return_value=current),
            ),
            patch(
                "services.chat_workspace_tools.runner.create_pending_approval",
                new=AsyncMock(return_value={"id": "approval-1", "status": "pending"}),
            ) as create_approval,
            patch("services.chat_workspace_tools.runner.execute_auto_approved", new=AsyncMock()) as execute,
        ):
            result = runner.run(
                state,
                _tool_call(PROFILE_SETTINGS_UPDATE_TOOL_NAME, bio="New bio"),
            )

        self.assertEqual(result["status"], "awaiting_user_approval")
        self.assertEqual(state.telemetry.workspace_auto_executions, 0)
        create_approval.assert_awaited_once()
        execute.assert_not_awaited()
        self.assertEqual(create_approval.await_args.kwargs["proposal"].preview["bio"], "New bio")

    def test_approval_execution_uses_the_same_session_and_does_not_write_theme_to_db(self):
        session = MagicMock()
        current = _profile()

        with patch(
            "services.chat_workspace_tools.profile.update_chat_profile_settings_if_unchanged",
            new=AsyncMock(return_value=True),
        ) as update:
            outcome = asyncio.run(
                _execute_profile_settings_update(
                    session,
                    7,
                    {"display_name": "Sora", "bio": "", "preferred_locale": "en", "theme": "dark"},
                    {
                        "user_id": 7,
                        "base_profile_fingerprint": profile_settings_fingerprint(current),
                    },
                )
            )

        self.assertEqual(outcome.target_id, 7)
        self.assertEqual(outcome.target_title, "")
        update.assert_awaited_once_with(
            7,
            expected_fingerprint=profile_settings_fingerprint(current),
            updates={"username": "Sora", "bio": "", "preferred_locale": "en"},
            session=session,
        )

    def test_theme_only_approval_does_not_compare_unrelated_profile_fields(self):
        session = MagicMock()
        with patch(
            "services.chat_workspace_tools.profile.update_chat_profile_settings_if_unchanged",
            new=AsyncMock(return_value=True),
        ) as update:
            outcome = asyncio.run(
                _execute_profile_settings_update(
                    session,
                    7,
                    {"theme": "dark"},
                    {"user_id": 7, "base_profile_fingerprint": "proposal-snapshot"},
                )
            )

        self.assertEqual(outcome.target_id, 7)
        update.assert_awaited_once_with(
            7,
            expected_fingerprint=None,
            updates={},
            session=session,
        )

    def test_approval_execution_rejects_another_user_and_a_changed_target(self):
        target_ref = {"user_id": 8, "base_profile_fingerprint": "snapshot"}
        with self.assertRaises(WorkspaceToolError) as ctx:
            asyncio.run(_execute_profile_settings_update(MagicMock(), 7, {"bio": "new"}, target_ref))
        self.assertEqual(ctx.exception.code, "target_not_found")

        with patch(
            "services.chat_workspace_tools.profile.update_chat_profile_settings_if_unchanged",
            new=AsyncMock(return_value=False),
        ):
            with self.assertRaises(WorkspaceToolError) as ctx:
                asyncio.run(
                    _execute_profile_settings_update(
                        MagicMock(),
                        7,
                        {"bio": "new"},
                        {"user_id": 7, "base_profile_fingerprint": "old"},
                    )
                )
        self.assertEqual(ctx.exception.code, "target_changed")


class UserRepositoryProfileCasTests(unittest.TestCase):
    def test_profile_read_selects_only_fields_exposed_to_the_tool(self):
        row = {
            "id": 7,
            "username": "Mika",
            "bio": "bio",
            "llm_profile_context": "context",
            "preferred_locale": "ja",
        }
        mapping_result = SimpleNamespace(first=Mock(return_value=row))
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=SimpleNamespace(mappings=Mock(return_value=mapping_result))
        )
        repository = UserRepository(session)

        profile = asyncio.run(repository.get_chat_profile_settings(7))
        selected_columns = [column.key for column in session.execute.await_args.args[0].selected_columns]

        self.assertEqual(profile, row)
        self.assertEqual(
            selected_columns,
            ["id", "username", "bio", "llm_profile_context", "preferred_locale"],
        )

    def test_changed_snapshot_is_not_updated(self):
        current = SimpleNamespace(
            username="changed",
            bio="bio",
            llm_profile_context="context",
            preferred_locale="ja",
        )
        session = MagicMock()
        session.scalar = AsyncMock(return_value=current)
        session.execute = AsyncMock()
        repository = UserRepository(session)

        updated = asyncio.run(
            repository.update_chat_profile_settings_if_unchanged(
                7,
                expected_fingerprint=profile_settings_fingerprint(
                    {"username": "old", "bio": "bio", "llm_profile_context": "context", "preferred_locale": "ja"}
                ),
                updates={"bio": "new"},
            )
        )

        self.assertFalse(updated)
        session.execute.assert_not_awaited()

    def test_matching_snapshot_updates_with_row_lock_and_supports_theme_only_noop(self):
        values = {"username": "Mika", "bio": "bio", "llm_profile_context": "context", "preferred_locale": "ja"}
        current = SimpleNamespace(**values)
        session = MagicMock()
        session.scalar = AsyncMock(return_value=current)
        session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
        repository = UserRepository(session)
        fingerprint = profile_settings_fingerprint(values)

        updated = asyncio.run(
            repository.update_chat_profile_settings_if_unchanged(
                7,
                expected_fingerprint=fingerprint,
                updates={"username": "Sora"},
            )
        )
        theme_only = asyncio.run(
            repository.update_chat_profile_settings_if_unchanged(
                7,
                expected_fingerprint=fingerprint,
                updates={},
            )
        )

        self.assertTrue(updated)
        self.assertTrue(theme_only)
        self.assertEqual(session.execute.await_count, 1)
        self.assertIsNotNone(session.scalar.await_args.args[0]._for_update_arg)

    def test_theme_only_noop_ignores_an_unrelated_profile_change(self):
        current = SimpleNamespace(
            username="new name",
            bio="new bio",
            llm_profile_context="new context",
            preferred_locale="en",
        )
        session = MagicMock()
        session.scalar = AsyncMock(return_value=current)
        session.execute = AsyncMock()
        repository = UserRepository(session)

        updated = asyncio.run(
            repository.update_chat_profile_settings_if_unchanged(
                7,
                expected_fingerprint=None,
                updates={},
            )
        )

        self.assertTrue(updated)
        session.execute.assert_not_awaited()
        self.assertIsNotNone(session.scalar.await_args.args[0]._for_update_arg)


class _LocaleReadSession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc_info):
        return False


class ProfileLocaleSessionSyncTests(unittest.IsolatedAsyncioTestCase):
    def _request(self, session: dict) -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/chat/tool-approvals/id/decision",
                "headers": [],
                "session": session,
                "state": {},
            }
        )

    async def _sync(self, request: Request, card: dict, persisted_locale: str | None):
        read_locale = AsyncMock(return_value=persisted_locale)
        with patch("blueprints.chat.tool_approvals.session_scope", _LocaleReadSession), patch(
            "blueprints.chat.tool_approvals.UserRepository.get_user_preferred_locale", read_locale
        ):
            locale = await _sync_approved_profile_locale(request, 7, card)
        return locale, read_locale

    async def test_successful_approved_locale_updates_the_existing_session_path(self):
        request = self._request({"user_id": 7})

        locale, read_locale = await self._sync(
            request,
            {
                "tool": PROFILE_SETTINGS_UPDATE_TOOL_NAME,
                "status": "succeeded",
                "preview": {"preferred_locale": "en"},
            },
            "en",
        )

        self.assertEqual(locale, "en")
        read_locale.assert_awaited_once_with(7)
        self.assertEqual(request.session["preferred_locale"], "en")
        self.assertTrue(request.session["_preferred_locale_loaded"])
        self.assertEqual(request.state.locale, "en")
        self.assertTrue(request.state.persist_locale_cookie)

    async def test_stale_approved_locale_syncs_to_the_persisted_value(self):
        # 承認済みカードの preview ではなく、DB に今ある言語へ合わせる
        # Sync to the locale persisted now, not the settled card's preview
        request = self._request({"user_id": 7, "preferred_locale": "ja"})

        locale, _ = await self._sync(
            request,
            {
                "tool": PROFILE_SETTINGS_UPDATE_TOOL_NAME,
                "status": "succeeded",
                "preview": {"preferred_locale": "en"},
            },
            "ja",
        )

        self.assertEqual(locale, "ja")
        self.assertEqual(request.session["preferred_locale"], "ja")
        self.assertEqual(request.state.locale, "ja")

    async def test_failed_or_denied_locale_proposal_does_not_change_the_session(self):
        request = self._request({"user_id": 7, "preferred_locale": "ja"})

        locale, read_locale = await self._sync(
            request,
            {
                "tool": PROFILE_SETTINGS_UPDATE_TOOL_NAME,
                "status": "failed",
                "preview": {"preferred_locale": "en"},
            },
            "en",
        )

        self.assertIsNone(locale)
        read_locale.assert_not_awaited()
        self.assertEqual(request.session["preferred_locale"], "ja")
        self.assertNotIn("locale", request.state)
