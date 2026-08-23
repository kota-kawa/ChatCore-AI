import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from starlette.responses import JSONResponse

from services.chat_use_case import ChatPostUseCase, ChatPostUseCaseDependencies
from tests.helpers.request_helpers import build_request


# トップページのチャット（未ログインの一時ルーム）で、発話に含まれるURLの本文が
# 参照資料として最後のユーザー発話へ注入されることを検証するテストクラス。
# Test class verifying that, in the top page chat (guest temporary room), the
# content behind URLs in the message is injected into the last user message.
class ChatUseCaseUrlContextTestCase(unittest.TestCase):
    # 依存関係と、生成プロンプトを捕捉するフックを構築します。
    # Build the dependency container plus a hook capturing the generated prompt.
    def _build_use_case(self):
        captured_context: dict = {}
        appended: list[tuple] = []

        async def require_json_dict(request):
            return await request.json(), None

        def validate_payload_model(data, model_cls, **_kwargs):
            return model_cls(**data), None

        def jsonify(payload, status_code=200):
            return JSONResponse(payload, status_code=status_code)

        async def validate_guest_room_access(_session, _chat_room_id):
            return "sid-1", None

        def build_context_messages(**kwargs):
            captured_context.update(kwargs)
            return kwargs["recent_messages"]

        ephemeral_store = SimpleNamespace(
            append_message=Mock(side_effect=lambda *args, **kwargs: appended.append(args)),
            get_messages=Mock(
                side_effect=lambda _sid, _room: [
                    {"role": role, "content": content}
                    for (_s, _r, role, content, *_rest) in appended
                ]
            ),
        )

        deps = ChatPostUseCaseDependencies(
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
            validate_guest_room_access=validate_guest_room_access,
            resolve_authenticated_room_target=Mock(),
            ensure_ephemeral_room=Mock(),
            get_temporary_user_store_key=Mock(return_value="tmp:guest"),
            ephemeral_store=ephemeral_store,
            save_message_to_db=Mock(),
            get_active_leaf_id=Mock(return_value=None),
            get_chat_room_messages=Mock(return_value=[]),
            get_room_web_search_contexts=Mock(return_value=[]),
            normalize_messages_for_llm=lambda messages: [
                {"role": item["role"], "content": str(item["content"]).replace("<br>", "\n")}
                for item in messages
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
            build_context_messages=build_context_messages,
            build_base_system_prompt=Mock(return_value="system"),
            build_generation_key=Mock(return_value="sid-1:room-1"),
            has_active_generation=Mock(return_value=False),
            consume_llm_daily_quota=Mock(return_value=(True, 1, 300)),
            cleanup_unanswered_user_messages=Mock(),
            get_seconds_until_daily_reset=Mock(return_value=60),
            is_streaming_model=Mock(return_value=False),
            search_personal_knowledge=Mock(return_value={"status": "no_results"}),
            search_shared_prompts=Mock(return_value={"status": "no_results"}),
            start_generation_job=Mock(),
            build_llm_stream_response=Mock(),
            iter_llm_stream_events=Mock(),
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
        return ChatPostUseCase(deps, default_model="test-model"), deps, captured_context

    # 指定した発話でユースケースを実行し、URL取得結果を差し替えたうえで生成文脈を返します。
    # Run the use case for a message with a stubbed URL fetcher, returning the built context.
    def _run(self, message: str, fetched: dict[str, str]):
        use_case, deps, captured_context = self._build_use_case()
        request = build_request(
            method="POST",
            path="/api/chat",
            json_body={
                "message": message,
                "chat_room_id": "room-1",
                "model": "test-model",
            },
            session={},
        )

        with (
            patch(
                "services.chat_use_case.fetch_urls_content",
                return_value=fetched,
            ) as mock_fetch,
            patch(
                "services.chat_use_case.maybe_augment_messages_with_web_search",
                side_effect=lambda messages, _model: SimpleNamespace(messages=messages, result=None),
            ),
            patch(
                "services.chat_use_case.normalize_response_with_artifact_retry",
                side_effect=lambda response, **_kwargs: SimpleNamespace(
                    text=response, parts=None, validation_errors=[]
                ),
            ) as mock_normalize,
        ):
            asyncio.run(
                use_case.execute(
                    request,
                    auth_limit_service=object(),
                    llm_daily_limit_service=object(),
                    chat_generation_service=object(),
                )
            )

        last_user_message = captured_context["recent_messages"][-1]["content"]
        self.assertEqual(mock_normalize.call_args.kwargs["ui_mode"], "2D")
        return last_user_message, mock_fetch, deps

    # 発話に含まれるURLの本文が取得され、最後のユーザー発話へ参照資料として付与されることを検証します。
    # Verify URL content is fetched and prepended to the last user message as reference material.
    def test_injects_fetched_url_content_into_last_user_message(self):
        message = "この記事を要約して https://example.com/article"
        content, mock_fetch, _deps = self._run(
            message,
            {"https://example.com/article": "記事の本文テキスト"},
        )

        mock_fetch.assert_called_once_with(["https://example.com/article"])
        self.assertIn('<url href="https://example.com/article">', content)
        self.assertIn("記事の本文テキスト", content)
        self.assertIn("<fetched_urls>", content)
        # 参照資料はユーザー発話の前に置かれ、発話自体も残ること
        # The reference material precedes the user's own message, which is preserved.
        self.assertTrue(content.startswith("<fetched_urls>"))
        self.assertIn("この記事を要約して", content)

    # 取得に失敗した場合、URLだけから推測しないよう指示するブロックが付与されることを検証します。
    # Verify a guard block is added when the fetch fails, telling the model not to guess.
    def test_adds_status_block_when_fetch_fails(self):
        content, _mock_fetch, _deps = self._run(
            "この記事を要約して https://example.com/article",
            {},
        )

        self.assertIn("<fetched_urls_status>", content)
        self.assertNotIn("<fetched_urls>", content)

    # URLを含まない発話では取得処理自体が行われないことを検証します。
    # Verify no fetch happens for messages without URLs.
    def test_skips_fetch_without_urls(self):
        content, mock_fetch, _deps = self._run("URLのない普通の質問です", {})

        mock_fetch.assert_not_called()
        self.assertNotIn("<fetched_urls", content)
        self.assertEqual(content, "URLのない普通の質問です")


if __name__ == "__main__":
    unittest.main()
