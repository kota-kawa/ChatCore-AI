"""記憶のまとめ（`<user_memory>`）が、新規投稿と再生成の経路で入る条件・入らない条件を検証するテスト（ADR 0025）。

Tests when the memory summary (`<user_memory>`) reaches the conversation on the post and regeneration paths, and when it must not.
"""

import asyncio
import dataclasses
import json
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

from services.chat_context import build_context_messages
from services.chat_regeneration_pipeline import (
    ChatRegenerationStreamStarted,
    run_chat_regeneration,
)
from services.chat_use_case import ChatPostUseCase
from services.user_memory import build_user_memory_summary
from tests.unit import test_chat_skill_selection_integration as regeneration_helpers
from tests.unit import test_chat_use_case_lookup_flags as post_helpers

# 記憶の文面に出てはいけない目印。ログへ漏れていないことの確認に使う。
# A marker that must never appear in a log line, to check memory text does not leak into logs.
_SECRET_TEXT = "SECRET-MEMORY-TEXT-4711"


def _summary():
    return build_user_memory_summary(
        [
            {
                "id": 1,
                "fact_type": "preference",
                "title": "回答の形式",
                "content": _SECRET_TEXT,
                "importance": 70,
                "last_mentioned_at": datetime(2026, 11, 18, 9, 0, tzinfo=UTC),
            }
        ]
    )


def _memory_messages(conversation_messages):
    return [message for message in conversation_messages if str(message["content"]).startswith("<user_memory>")]


# 投稿（ChatPostUseCase）の経路。
# The post path (ChatPostUseCase).
class UserMemoryOnPostPathTestCase(unittest.TestCase):
    def _deps(self, *, user=None, streaming=True, summary=None):
        helper = post_helpers.ChatUseCaseLookupFlagsTestCase()
        deps = helper._build_deps(Mock())
        object.__setattr__(deps.prompts, "build_context_messages", build_context_messages)
        deps.get_user_by_id.return_value = {"id": 42, "memory_use_enabled": True} if user is None else user
        deps.load_user_memory_summary.return_value = _summary() if summary is None else summary
        deps.is_streaming_model.return_value = streaming
        return helper, deps

    def _run_stream(self, helper, deps, *, session=None):
        helper._run(deps, body_extra={}, session={"user_id": 42} if session is None else session)
        return deps.start_generation_job.call_args.kwargs

    def test_a_new_rooms_first_turn_already_carries_the_summary(self):
        # ヘルパーの既定は初回ターン。ルームの要約は読まないが、記憶のまとめはこの分岐の外で読む。
        # The helper stands in for a first turn: the room summary is skipped, the memory summary is not.
        helper, deps = self._deps()

        kwargs = self._run_stream(helper, deps)

        deps.load_user_memory_summary.assert_awaited_once_with(42)
        deps.get_room_summary.assert_not_called()
        (message,) = _memory_messages(kwargs["conversation_messages"])
        self.assertIn(_SECRET_TEXT, message["content"])
        self.assertEqual(message["role"], "system")

    def test_a_later_turn_carries_the_summary_too(self):
        helper, deps = self._deps()
        deps.store_user_message_and_load_turn_context.side_effect = lambda _room, message, *_a, **_k: {
            "message_id": 3,
            "parent_message_id": 2,
            "is_first_turn": False,
            "messages": [
                {"role": "user", "content": "前の質問"},
                {"role": "assistant", "content": "前の回答"},
                {"role": "user", "content": message},
            ],
            "web_search_contexts": [],
        }

        kwargs = self._run_stream(helper, deps)

        deps.get_room_summary.assert_called_once()
        self.assertEqual(len(_memory_messages(kwargs["conversation_messages"])), 1)

    def test_the_job_is_given_the_summary_size_only_when_one_was_added(self):
        helper, deps = self._deps()
        self.assertEqual(self._run_stream(helper, deps)["user_memory"].fact_count, 1)

        helper, deps = self._deps(user={"id": 42, "memory_use_enabled": False})
        self.assertNotIn("user_memory", self._run_stream(helper, deps))

    def test_the_non_streaming_path_carries_the_summary(self):
        _, deps = self._deps(streaming=False)

        use_case = ChatPostUseCase(deps, default_model="test-model")
        request = post_helpers.build_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "room-1", "model": "test-model"},
            session={"user_id": 42},
        )
        with patch("services.chat_use_case.generate_chat_room_title", return_value=None):
            asyncio.run(
                use_case.execute(
                    request,
                    auth_limit_service=object(),
                    llm_daily_limit_service=object(),
                    chat_generation_service=object(),
                )
            )

        sent = deps.get_llm_response.call_args_list[0].args[0]
        self.assertEqual(len(_memory_messages(sent)), 1)

    def test_temporary_chat_never_reads_or_carries_the_summary(self):
        helper, deps = self._deps()
        deps.resolve_authenticated_room_target.return_value = ("temporary", "sid-1", None)

        kwargs = self._run_stream(helper, deps)

        deps.load_user_memory_summary.assert_not_called()
        self.assertEqual(_memory_messages(kwargs["conversation_messages"]), [])

    def test_guest_never_reads_or_carries_the_summary(self):
        helper, deps = self._deps()

        kwargs = self._run_stream(helper, deps, session={})

        deps.load_user_memory_summary.assert_not_called()
        self.assertEqual(_memory_messages(kwargs["conversation_messages"]), [])

    def test_a_disabled_setting_keeps_the_summary_out(self):
        helper, deps = self._deps(user={"id": 42, "memory_use_enabled": False})

        kwargs = self._run_stream(helper, deps)

        deps.load_user_memory_summary.assert_not_called()
        self.assertEqual(_memory_messages(kwargs["conversation_messages"]), [])

    def test_an_unreadable_user_row_counts_as_off(self):
        for label, user_lookup in (
            ("missing row", {"return_value": None}),
            ("read failure", {"side_effect": RuntimeError("db down")}),
            ("no setting value", {"return_value": {"id": 42}}),
        ):
            with self.subTest(label):
                helper, deps = self._deps()
                deps.get_user_by_id.configure_mock(**user_lookup)

                kwargs = self._run_stream(helper, deps)

                deps.load_user_memory_summary.assert_not_called()
                self.assertEqual(_memory_messages(kwargs["conversation_messages"]), [])

    def test_a_failed_read_does_not_stop_the_answer_and_logs_no_memory_text(self):
        helper, deps = self._deps()
        deps.load_user_memory_summary.side_effect = RuntimeError(f"boom while reading {_SECRET_TEXT}")

        kwargs = self._run_stream(helper, deps)

        # 回答の生成は続き、記憶のまとめだけが入らない。
        # Generation continues; only the summary is missing.
        self.assertEqual(_memory_messages(kwargs["conversation_messages"]), [])
        logged = " ".join(str(call) for call in deps.logger.warning.call_args_list)
        self.assertIn("Failed to load user memory", logged)
        self.assertNotIn(_SECRET_TEXT, logged)

    # --- 記憶の検索ツール（memory_search）の提供条件。`<user_memory>` と同じ条件で、「＋→メモ」のトグルに依らない。
    # --- Offering the memory_search tool: the same condition as `<user_memory>`, independent of the "+ -> Memo" toggle.
    def test_the_memory_search_tool_is_offered_on_every_turn_of_a_normal_room_whatever_the_toggle_says(self):
        for toggle in (False, True):
            with self.subTest(memo_toggle=toggle):
                helper, deps = self._deps()
                helper._run(deps, body_extra={"use_personal_knowledge": toggle}, session={"user_id": 42})
                kwargs = deps.start_generation_job.call_args.kwargs

                self.assertIsNotNone(kwargs["memory_search"])
                # 事前の検索はしない（モデルが呼んだときだけ動く）。
                # Nothing is prefetched: it runs only when the model calls it.
                deps.search_memory.assert_not_called()
                self.assertEqual([m for m in kwargs["conversation_messages"] if "memory_search_result" in str(m["content"])], [])

    def test_the_memory_search_tool_is_not_offered_for_a_temporary_chat_a_guest_or_an_unusable_setting(self):
        def temporary(deps):
            deps.resolve_authenticated_room_target.return_value = ("temporary", "sid-1", None)

        for label, setup, session in (
            ("temporary chat", temporary, {"user_id": 42}),
            ("guest", lambda deps: None, {}),
            (
                "disabled",
                lambda deps: deps.get_user_by_id.configure_mock(return_value={"id": 42, "memory_use_enabled": False}),
                {"user_id": 42},
            ),
            ("no setting value", lambda deps: deps.get_user_by_id.configure_mock(return_value={"id": 42}), {"user_id": 42}),
            ("missing row", lambda deps: deps.get_user_by_id.configure_mock(return_value=None), {"user_id": 42}),
            ("read failure", lambda deps: deps.get_user_by_id.configure_mock(side_effect=RuntimeError("db down")), {"user_id": 42}),
        ):
            with self.subTest(label):
                helper, deps = self._deps()
                setup(deps)
                helper._run(deps, body_extra={"use_personal_knowledge": True}, session=session)

                self.assertIsNone(deps.start_generation_job.call_args.kwargs["memory_search"])

    def test_the_memo_toggle_does_not_search_memory_before_generation(self):
        # 「＋→メモ」がオンでも、事前の検索はメモだけ。記憶の検索関数は呼ばれない。
        # With the memo toggle on, the prefetch covers memos only: the memory search function is not called.
        helper, deps = self._deps()

        helper._run(deps, body_extra={"use_personal_knowledge": True}, session={"user_id": 42})

        deps.search_memory.assert_not_called()

    def test_a_non_streaming_turn_runs_without_the_tool_as_before(self):
        _, deps = self._deps(streaming=False)

        use_case = ChatPostUseCase(deps, default_model="test-model")
        request = post_helpers.build_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "room-1", "model": "test-model"},
            session={"user_id": 42},
        )
        with patch("services.chat_use_case.generate_chat_room_title", return_value=None):
            asyncio.run(
                use_case.execute(
                    request,
                    auth_limit_service=object(),
                    llm_daily_limit_service=object(),
                    chat_generation_service=object(),
                )
            )

        deps.start_generation_job.assert_not_called()
        deps.search_memory.assert_not_called()


# 再生成・編集して再生成の経路（run_chat_regeneration）。
# The regeneration paths (run_chat_regeneration), which serve both regenerate and edit-and-regenerate.
class UserMemoryOnRegenerationPathTestCase(unittest.TestCase):
    def _run(self, *, user=None, room_mode="normal", load=None, streaming=True, use_personal_knowledge=False):
        helper = regeneration_helpers.ChatSkillSelectionIntegrationTests()
        pipeline_input = helper._regeneration_input(
            streaming=streaming, room_mode=room_mode, user={"id": 42, "memory_use_enabled": True} if user is None else user
        )
        pipeline_input = dataclasses.replace(pipeline_input, use_personal_knowledge=use_personal_knowledge)
        load = load or AsyncMock(return_value=_summary())
        deps = dataclasses.replace(pipeline_input.dependencies, load_user_memory_summary=load)
        pipeline_input = dataclasses.replace(pipeline_input, dependencies=deps)
        decision = json.dumps({"selected_skill_ids": [], "uncertain": False, "ui_mode": "NONE"})
        with (
            patch("services.chat_regeneration_pipeline.fetch_pasted_url_context", return_value=((), "")),
            patch("services.chat_regeneration_pipeline.has_active_generation", return_value=False),
            patch("services.chat_regeneration_pipeline.start_generation_job", return_value=Mock()) as start,
            patch("services.chat_skill_selection.get_llm_json_response", return_value=decision),
        ):
            outcome = asyncio.run(run_chat_regeneration(pipeline_input))
        return outcome, start, load, deps

    def test_regeneration_carries_the_summary(self):
        outcome, start, load, _ = self._run()

        self.assertIsInstance(outcome, ChatRegenerationStreamStarted)
        load.assert_awaited_once_with(42)
        self.assertEqual(len(_memory_messages(start.call_args.kwargs["conversation_messages"])), 1)
        self.assertEqual(start.call_args.kwargs["user_memory"].fact_count, 1)

    def test_the_non_streaming_regeneration_carries_the_summary(self):
        _, _, load, deps = self._run(streaming=False)

        load.assert_awaited_once_with(42)
        self.assertEqual(len(_memory_messages(deps.get_llm_response.call_args.args[0])), 1)

    def test_temporary_disabled_and_unreadable_cases_keep_the_summary_out(self):
        for label, kwargs in (
            ("temporary chat", {"room_mode": "temporary"}),
            ("disabled", {"user": {"id": 42, "memory_use_enabled": False}}),
            ("no setting value", {"user": {"id": 42}}),
        ):
            with self.subTest(label):
                _, start, load, _ = self._run(**kwargs)

                load.assert_not_called()
                self.assertEqual(_memory_messages(start.call_args.kwargs["conversation_messages"]), [])
                self.assertNotIn("user_memory", start.call_args.kwargs)

    def test_regeneration_offers_the_memory_search_tool_on_the_same_terms(self):
        for toggle in (False, True):
            with self.subTest(memo_toggle=toggle):
                outcome, start, _, deps = self._run(use_personal_knowledge=toggle)

                self.assertIsInstance(outcome, ChatRegenerationStreamStarted)
                self.assertIsNotNone(start.call_args.kwargs["memory_search"])
                deps.search_memory.assert_not_called()

    def test_regeneration_does_not_offer_it_for_a_temporary_chat_a_switched_off_setting_or_an_unreadable_row(self):
        for label, kwargs in (
            ("temporary chat", {"room_mode": "temporary"}),
            ("disabled", {"user": {"id": 42, "memory_use_enabled": False}}),
            ("no setting value", {"user": {"id": 42}}),
        ):
            with self.subTest(label):
                _, start, _, _ = self._run(use_personal_knowledge=True, **kwargs)

                self.assertIsNone(start.call_args.kwargs["memory_search"])

    def test_the_non_streaming_regeneration_never_starts_a_job_with_the_tool(self):
        _, start, _, deps = self._run(streaming=False)

        start.assert_not_called()
        deps.search_memory.assert_not_called()

    def test_a_failed_read_does_not_stop_regeneration_and_logs_no_memory_text(self):
        load = AsyncMock(side_effect=RuntimeError(f"boom while reading {_SECRET_TEXT}"))

        outcome, start, _, deps = self._run(load=load)

        self.assertIsInstance(outcome, ChatRegenerationStreamStarted)
        self.assertEqual(_memory_messages(start.call_args.kwargs["conversation_messages"]), [])
        logged = " ".join(str(call) for call in deps.logger.warning.call_args_list)
        self.assertIn("memory", logged)
        self.assertNotIn(_SECRET_TEXT, logged)


if __name__ == "__main__":
    unittest.main()
