import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from starlette.responses import JSONResponse

from services.chat_use_case import ChatPostUseCase, ChatPostUseCaseDependencies
from tests.helpers.request_helpers import build_request


# 日本語: await される依存をモックするための、固定値を返す非同期関数を作ります。
# English: Build an awaitable dependency stub that resolves to a fixed value.
def _async_return(value):
    async def _call(*_args, **_kwargs):
        return value

    return _call


# 日本語: メモ・共有プロンプトの参照フラグが生成ジョブまで正しく伝わるかを検証するテスト。
# English: Verify the memo and shared-prompt flags reach the generation job exactly when they should.
class ChatUseCaseLookupFlagsTestCase(unittest.TestCase):
    def _build_deps(self, search_personal_knowledge, search_shared_prompts=None):
        async def require_json_dict(request):
            return await request.json(), None

        def validate_payload_model(data, model_cls, **_kwargs):
            return model_cls(**data), None

        def jsonify(payload, status_code=200):
            return JSONResponse(payload, status_code=status_code)

        return ChatPostUseCaseDependencies(
            cleanup_ephemeral_chats=Mock(),
            require_json_dict=require_json_dict,
            validate_payload_model=validate_payload_model,
            jsonify=jsonify,
            jsonify_rate_limited=Mock(),
            jsonify_service_error=Mock(),
            log_and_internal_server_error=Mock(),
            validate_model_name=Mock(),
            consume_guest_chat_daily_limit=Mock(return_value=(True, None)),
            get_seconds_until_tomorrow=Mock(return_value=60),
            validate_guest_room_access=_async_return(("sid-1", None)),
            resolve_authenticated_room_target=Mock(return_value=("normal", None, None)),
            ensure_ephemeral_room=Mock(),
            get_temporary_user_store_key=Mock(return_value="tmp:user:42"),
            ephemeral_store=SimpleNamespace(
                append_message=Mock(),
                get_messages=Mock(return_value=[]),
            ),
            save_message_to_db=Mock(return_value=1),
            get_active_leaf_id=Mock(return_value=None),
            get_chat_room_messages=Mock(return_value=[{"role": "user", "content": "質問"}]),
            get_room_web_search_contexts=Mock(return_value=[]),
            normalize_messages_for_llm=lambda messages: [
                {"role": item["role"], "content": str(item["content"])} for item in messages
            ],
            find_latest_task_launch_request=Mock(return_value=None),
            load_task_prompt_data=Mock(),
            build_task_prompt=Mock(return_value=None),
            get_user_by_id=Mock(return_value={}),
            build_user_profile_prompt=Mock(return_value=None),
            get_room_summary=Mock(return_value={"summary": ""}),
            list_room_memory_facts=Mock(return_value=[]),
            remember_facts_from_message=Mock(return_value=[]),
            rename_chat_room_if_current_title_in=Mock(return_value=False),
            load_project_context=Mock(return_value=None),
            build_context_messages=lambda **kwargs: kwargs["recent_messages"],
            build_base_system_prompt=Mock(return_value="system"),
            build_generation_key=Mock(return_value="user:42:room-1"),
            has_active_generation=Mock(return_value=False),
            consume_llm_daily_quota=Mock(return_value=(True, 1, 300)),
            cleanup_unanswered_user_messages=Mock(),
            get_seconds_until_daily_reset=Mock(return_value=60),
            is_streaming_model=Mock(return_value=True),
            search_personal_knowledge=search_personal_knowledge,
            search_shared_prompts=search_shared_prompts or Mock(return_value={"status": "no_results"}),
            start_generation_job=Mock(return_value=SimpleNamespace()),
            build_llm_stream_response=Mock(return_value=JSONResponse({"streaming": True})),
            iter_llm_stream_events=Mock(return_value=iter(())),
            get_llm_response=Mock(return_value="assistant reply"),
            decide_generative_ui_mode=Mock(return_value="2D"),
            is_retryable_llm_error=Mock(return_value=False),
            rebuild_room_summary=Mock(),
            should_extract_context=Mock(return_value=False),
            schedule_context_extraction=Mock(),
            submit_background_task=Mock(),
            get_session_id=Mock(return_value="sid-1"),
            logger=Mock(),
        )

    def _run(self, deps, *, body_extra, session, key="personal_knowledge_search"):
        use_case = ChatPostUseCase(deps, default_model="test-model")
        request = build_request(
            method="POST",
            path="/api/chat",
            json_body={
                "message": "去年の沖縄旅行の予算は？",
                "chat_room_id": "room-1",
                "model": "test-model",
                **body_extra,
            },
            session=session,
        )
        with (
            patch("services.chat_use_case.generate_chat_room_title", return_value=None),
        ):
            asyncio.run(
                use_case.execute(
                    request,
                    auth_limit_service=object(),
                    llm_daily_limit_service=object(),
                    chat_generation_service=object(),
                )
            )
        return deps.start_generation_job.call_args.kwargs[key]

    # 日本語: 有効時は生成前に必ず検索し、追加検索用の関数もユーザーIDに束ねてジョブへ渡します。
    # English: When enabled, lookup runs before generation and the job also receives a user-bound retry.
    def test_enabled_request_passes_a_user_scoped_lookup(self):
        search = Mock(return_value={"status": "ok", "memo_count": 1})
        deps = self._build_deps(search)

        lookup = self._run(
            deps,
            body_extra={"use_personal_knowledge": True},
            session={"user_id": 42},
        )

        self.assertIsNotNone(lookup)
        self.assertEqual(deps.start_generation_job.call_args.kwargs["ui_mode"], "2D")
        deps.decide_generative_ui_mode.assert_called_once()
        search.assert_called_once_with(42, "去年の沖縄旅行の予算は？")
        trace = deps.start_generation_job.call_args.kwargs["selected_reference_trace"]
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0].payload["memo_count"], 1)
        lookup("沖縄")
        self.assertEqual(
            search.call_args_list,
            [
                call(42, "去年の沖縄旅行の予算は？"),
                call(42, "沖縄"),
            ],
        )

    # 日本語: 未指定なら検索関数は渡さず、従来どおりの生成になります。
    # English: Without the flag, no lookup is wired up and generation is unchanged.
    def test_request_without_the_flag_passes_no_lookup(self):
        deps = self._build_deps(Mock())

        lookup = self._run(deps, body_extra={}, session={"user_id": 42})

        self.assertIsNone(lookup)

    def test_disabled_generative_ui_skill_skips_mode_decision(self):
        deps = self._build_deps(Mock())
        deps.get_user_by_id.return_value = {"generative_ui_skill_enabled": False}

        self._run(deps, body_extra={}, session={"user_id": 42})

        deps.decide_generative_ui_mode.assert_not_called()
        self.assertEqual(deps.start_generation_job.call_args.kwargs["ui_mode"], "NONE")

    # 日本語: メモは本人のデータなので、ゲストにはフラグがあっても渡しません。
    # English: Memos are owner-only data, so a guest never gets the lookup even with the flag.
    def test_guest_request_never_gets_the_lookup(self):
        deps = self._build_deps(Mock())

        lookup = self._run(deps, body_extra={"use_personal_knowledge": True}, session={})

        self.assertIsNone(lookup)

    # 日本語: 未ログインで無効化されたメモ参照は、黙って落とさずモデルへ伝えます。
    # English: A memo lookup dropped for a signed-out session is reported, not silently ignored.
    def test_guest_request_is_told_the_memo_lookup_was_unavailable(self):
        deps = self._build_deps(Mock())

        self._run(deps, body_extra={"use_personal_knowledge": True}, session={})

        messages = deps.start_generation_job.call_args.kwargs["conversation_messages"]
        context = "\n".join(
            message["content"] for message in messages if message["role"] == "system"
        )
        self.assertIn("could not be used this turn", context)
        self.assertIn("signed out", context)



    # 日本語: 共有プロンプトは公開データなので、有効時は公開検索へ委譲する関数を渡します。
    # English: Shared prompts are public, so an enabled turn gets a lookup delegating to the public search.
    def test_shared_prompt_flag_passes_the_public_lookup(self):
        shared_search = Mock(return_value={"status": "ok", "prompt_count": 1})
        deps = self._build_deps(Mock(), shared_search)

        lookup = self._run(
            deps,
            body_extra={"use_shared_prompts": True},
            session={"user_id": 42},
            key="shared_prompt_search",
        )

        self.assertIsNotNone(lookup)
        shared_search.assert_called_once_with("去年の沖縄旅行の予算は？")
        lookup("議事録テンプレ")
        self.assertEqual(
            [item.args[0] for item in shared_search.call_args_list],
            ["去年の沖縄旅行の予算は？", "議事録テンプレ"],
        )

    # 日本語: 公開データなので、ゲストのリクエストでも共有プロンプト検索は使えます。
    # English: Being public data, the shared-prompt lookup is available to guests as well.
    def test_guest_request_can_search_shared_prompts(self):
        shared_search = Mock(return_value={"status": "ok", "prompt_count": 1})
        deps = self._build_deps(Mock(), shared_search)

        lookup = self._run(
            deps,
            body_extra={"use_shared_prompts": True},
            session={},
            key="shared_prompt_search",
        )

        self.assertIsNotNone(lookup)
        shared_search.assert_called_once_with("去年の沖縄旅行の予算は？")

    # 日本語: 事前検索済みのクエリをモデルが再度ツールで引いても、同じ本文は二度入りません。
    # English: A tool call repeating an already prefetched query does not re-inject the same bodies.
    def test_repeated_tool_query_is_not_searched_twice(self):
        shared_search = Mock(
            return_value={
                "status": "ok",
                "prompt_count": 1,
                "prompts": [{"title": "旅行計画テンプレ", "content": "予算を項目別に整理する"}],
            }
        )
        deps = self._build_deps(Mock(), shared_search)

        lookup = self._run(
            deps,
            body_extra={"use_shared_prompts": True},
            session={"user_id": 42},
            key="shared_prompt_search",
        )

        payload = lookup("去年の沖縄旅行の予算は？")

        shared_search.assert_called_once_with("去年の沖縄旅行の予算は？")
        self.assertEqual(payload["status"], "already_searched")
        self.assertNotIn("prompts", payload)

    # 日本語: 未指定なら共有プロンプト検索は渡しません。
    # English: Without the flag, no shared-prompt lookup is wired up.
    def test_request_without_the_shared_prompt_flag_passes_no_lookup(self):
        deps = self._build_deps(Mock())

        lookup = self._run(deps, body_extra={}, session={"user_id": 42}, key="shared_prompt_search")

        self.assertIsNone(lookup)

    # 日本語: ツール呼び出しを使わないモデルでも、選択した参照元を事前検索して回答へ渡します。
    # English: Non-streaming models also receive prefetched selected references without tool calls.
    def test_non_streaming_request_prefetches_selected_references(self):
        personal_search = Mock(
            return_value={
                "status": "ok",
                "memo_count": 1,
                "context_fact_count": 0,
                "memos": [{"title": "沖縄旅行", "content": "予算は10万円"}],
                "context_facts": [],
            }
        )
        shared_search = Mock(
            return_value={
                "status": "ok",
                "prompt_count": 1,
                "prompts": [{"title": "旅行計画テンプレ"}],
            }
        )
        deps = self._build_deps(personal_search, shared_search)
        deps.is_streaming_model.return_value = False
        request = build_request(
            method="POST",
            path="/api/chat",
            json_body={
                "message": "去年の沖縄旅行の予算は？",
                "chat_room_id": "room-1",
                "model": "test-model",
                "use_personal_knowledge": True,
                "use_shared_prompts": True,
            },
            session={"user_id": 42},
        )

        with (
            patch("services.chat_use_case.generate_chat_room_title", return_value=None),
        ):
            asyncio.run(
                ChatPostUseCase(deps, default_model="test-model").execute(
                    request,
                    auth_limit_service=object(),
                    llm_daily_limit_service=object(),
                    chat_generation_service=object(),
                )
            )

        personal_search.assert_called_once_with(42, "去年の沖縄旅行の予算は？")
        shared_search.assert_called_once_with("去年の沖縄旅行の予算は？")
        response_messages = deps.get_llm_response.call_args.args[0]
        selected_context = next(
            message["content"]
            for message in response_messages
            if "<selected_reference_context>" in str(message.get("content") or "")
        )
        self.assertIn("沖縄旅行", selected_context)
        self.assertIn("旅行計画テンプレ", selected_context)
        deps.start_generation_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
