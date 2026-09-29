"""Exercise the real selector at both chat orchestration boundaries without provider calls."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from services.chat_context import build_context_messages
from services.chat_regeneration_pipeline import (
    ChatRegenerationDependencies,
    ChatRegenerationInput,
    ChatRegenerationLogMessages,
    ChatRegenerationStreamStarted,
    run_chat_regeneration,
)
from services.chat_skill_selection import select_chat_skills
from services.chat_workspace_tools.profile import (
    PROFILE_SETTINGS_READ_TOOL_NAME,
    PROFILE_SETTINGS_UPDATE_TOOL_NAME,
)
from services.user_skills import GENERATIVE_UI_EXECUTION_CONTRACT, MEMO_TOOLS_SKILL_INSTRUCTIONS
from tests.unit import test_chat_use_case_lookup_flags as post_helpers


class ChatSkillSelectionIntegrationTests(unittest.TestCase):
    def _decision(self, ids, ui_mode="NONE"):
        return json.dumps({"selected_skill_ids": ids, "uncertain": False, "ui_mode": ui_mode})

    def test_post_selected_memo_carries_instructions_and_tools_together(self):
        helper = post_helpers.ChatUseCaseLookupFlagsTestCase()
        deps = helper._build_deps(Mock())
        object.__setattr__(deps.generation, "select_chat_skills", select_chat_skills)
        object.__setattr__(deps.prompts, "build_context_messages", build_context_messages)
        deps.get_user_by_id.return_value = {"id": 42}
        with patch("services.chat_skill_selection.get_llm_json_response", return_value=self._decision([-1])) as decision:
            helper._run(deps, body_extra={}, session={"user_id": 42})
        decision.assert_called_once()
        kwargs = deps.start_generation_job.call_args.kwargs
        prompt = str(kwargs["conversation_messages"])
        self.assertIn(MEMO_TOOLS_SKILL_INSTRUCTIONS.splitlines()[0], prompt)
        self.assertNotIn(GENERATIVE_UI_EXECUTION_CONTRACT, prompt)
        self.assertTrue(kwargs["workspace_tools"].handles("memo_create"))
        self.assertFalse(kwargs["explicit_ui_opt_out"])
        self.assertEqual(kwargs["ui_mode"], "NONE")

    def test_post_empty_selection_does_not_disable_the_ui_setting(self):
        helper = post_helpers.ChatUseCaseLookupFlagsTestCase()
        deps = helper._build_deps(Mock())
        object.__setattr__(deps.generation, "select_chat_skills", select_chat_skills)
        object.__setattr__(deps.prompts, "build_context_messages", build_context_messages)
        deps.get_user_by_id.return_value = {"id": 42}
        with patch("services.chat_skill_selection.get_llm_json_response", return_value=self._decision([])):
            helper._run(deps, body_extra={}, session={"user_id": 42})
        kwargs = deps.start_generation_job.call_args.kwargs
        workspace_tools = kwargs["workspace_tools"]
        self.assertEqual(
            {definition["function"]["name"] for definition in workspace_tools.definitions()},
            {PROFILE_SETTINGS_READ_TOOL_NAME, PROFILE_SETTINGS_UPDATE_TOOL_NAME},
        )
        self.assertFalse(kwargs["explicit_ui_opt_out"])
        self.assertNotIn("<enabled_user_skills>", str(kwargs["conversation_messages"]))

    def test_post_selection_does_not_read_fetched_content(self):
        helper = post_helpers.ChatUseCaseLookupFlagsTestCase()
        deps = helper._build_deps(Mock())
        object.__setattr__(deps.generation, "select_chat_skills", select_chat_skills)
        object.__setattr__(deps.prompts, "build_context_messages", build_context_messages)
        with (
            patch("services.chat_use_case.fetch_pasted_url_context", return_value=((), "EXTERNAL-SELECT-MEMO")),
            patch("services.chat_skill_selection.get_llm_json_response", return_value=self._decision([])) as decision,
        ):
            helper._run(deps, body_extra={}, session={"user_id": 42})
        self.assertNotIn("EXTERNAL-SELECT-MEMO", str(decision.call_args))
        self.assertIn("EXTERNAL-SELECT-MEMO", str(deps.start_generation_job.call_args.kwargs["conversation_messages"]))

    def _regeneration_input(self, *, streaming=True, user=None, room_mode="normal", theme_preference=None):
        deps = ChatRegenerationDependencies(
            logger=Mock(), ephemeral_store=SimpleNamespace(append_message=Mock()),
            load_task_prompt_data=AsyncMock(return_value=None),
            load_project_context_for_room=AsyncMock(return_value="Project guidance"),
            list_enabled_user_skills=AsyncMock(return_value=[]),
            get_user_by_id=AsyncMock(return_value=user if user is not None else {"id": 42}),
            get_room_summary=AsyncMock(return_value={}), list_room_memory_facts=AsyncMock(return_value=[]),
            get_room_web_search_contexts=AsyncMock(return_value=[]),
            consume_llm_daily_quota=Mock(return_value=(True, 1, 300)), check_usage_limit=AsyncMock(return_value=None),
            is_streaming_model=Mock(return_value=streaming),
            search_personal_knowledge=AsyncMock(), search_shared_prompts=AsyncMock(),
            get_llm_response=Mock(return_value="answer"), save_message_to_db=AsyncMock(return_value=1),
            get_chat_room_messages=AsyncMock(return_value=[]), rebuild_room_summary=AsyncMock(),
            cleanup_unanswered_user_messages=AsyncMock(),
        )
        return ChatRegenerationInput(
            dependencies=deps, log_messages=ChatRegenerationLogMessages("profile", "summary", "memory", "rebuild"),
            chat_room_id="room-1", model="test-model", user_id=42, sid="sid-1", room_mode=room_mode,
            all_messages=[{"role": "user", "content": "それを保存して"}],
            assistant_parent_id=1, use_personal_knowledge=False, use_shared_prompts=False, locale="ja",
            theme_preference=theme_preference,
        )

    def test_regeneration_passes_the_current_browser_theme_to_profile_tools(self):
        pipeline_input = self._regeneration_input(theme_preference="dark")
        with (
            patch("services.chat_regeneration_pipeline.fetch_pasted_url_context", return_value=((), "")),
            patch("services.chat_regeneration_pipeline.has_active_generation", return_value=False),
            patch("services.chat_regeneration_pipeline.start_generation_job", return_value=Mock()) as start,
            patch("services.chat_skill_selection.get_llm_json_response", return_value=self._decision([-1])),
        ):
            asyncio.run(run_chat_regeneration(pipeline_input))

        self.assertEqual(start.call_args.kwargs["workspace_tools"].browser_theme_preference, "dark")

    def test_regeneration_reselects_and_filters_external_reference_text(self):
        pipeline_input = self._regeneration_input()
        captured = []
        def decide(messages, _model):
            captured.append(messages)
            return self._decision([-1])
        with (
            patch("services.chat_regeneration_pipeline.fetch_pasted_url_context", return_value=((), "EXTERNAL-INSTRUCTION")),
            patch("services.chat_regeneration_pipeline.has_active_generation", return_value=False),
            patch("services.chat_regeneration_pipeline.start_generation_job", return_value=Mock()) as start,
            patch("services.chat_skill_selection.get_llm_json_response", side_effect=decide),
        ):
            result = asyncio.run(run_chat_regeneration(pipeline_input))
        self.assertIsInstance(result, ChatRegenerationStreamStarted)
        self.assertEqual(len(captured), 1)
        self.assertNotIn("EXTERNAL-INSTRUCTION", str(captured))
        self.assertIn("Project guidance", str(captured))
        kwargs = start.call_args.kwargs
        self.assertIn("EXTERNAL-INSTRUCTION", str(kwargs["conversation_messages"]))
        self.assertTrue(kwargs["workspace_tools"].handles("memo_edit"))
        self.assertFalse(kwargs["explicit_ui_opt_out"])

    def test_regeneration_quota_rejection_never_selects(self):
        pipeline_input = self._regeneration_input()
        pipeline_input.dependencies.consume_llm_daily_quota.return_value = (False, 1, 1)
        with (
            patch("services.chat_regeneration_pipeline.fetch_pasted_url_context", return_value=((), "")),
            patch("services.chat_regeneration_pipeline.has_active_generation", return_value=False),
            patch("services.chat_skill_selection.get_llm_json_response") as decision,
        ):
            asyncio.run(run_chat_regeneration(pipeline_input))
        decision.assert_not_called()

    def test_regeneration_fallback_still_excludes_ineligible_memo_tools(self):
        for room_mode in ("normal", "temporary"):
            with self.subTest(room_mode=room_mode):
                pipeline_input = self._regeneration_input(
                    room_mode=room_mode,
                    user={"id": 42, "memo_tools_skill_enabled": False, "prompt_tools_skill_enabled": False},
                )
                with (
                    patch("services.chat_regeneration_pipeline.fetch_pasted_url_context", return_value=((), "")),
                    patch("services.chat_regeneration_pipeline.has_active_generation", return_value=False),
                    patch("services.chat_regeneration_pipeline.start_generation_job", return_value=Mock()) as start,
                    patch("services.chat_skill_selection.get_llm_json_response", return_value="bad json"),
                ):
                    asyncio.run(run_chat_regeneration(pipeline_input))
                workspace_tools = start.call_args.kwargs.get("workspace_tools")
                if room_mode == "normal":
                    self.assertIsNotNone(workspace_tools)
                    self.assertEqual(
                        {definition["function"]["name"] for definition in workspace_tools.definitions()},
                        {PROFILE_SETTINGS_READ_TOOL_NAME, PROFILE_SETTINGS_UPDATE_TOOL_NAME},
                    )
                else:
                    self.assertIsNone(workspace_tools)
                self.assertNotIn(MEMO_TOOLS_SKILL_INSTRUCTIONS, str(start.call_args.kwargs["conversation_messages"]))
