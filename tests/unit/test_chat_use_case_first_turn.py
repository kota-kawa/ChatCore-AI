import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from starlette.responses import JSONResponse

from services.chat_use_case import ChatPostUseCase, ChatPostUseCaseDependencies
from tests.helpers.request_helpers import build_request


# チャットの最初の発話（First Turn）において、不要なルーム履歴クエリがスキップされることを検証するテストクラス。
# Test class to verify that empty/unnecessary room context queries are skipped during the first turn of a chat session.
class ChatUseCaseFirstTurnTestCase(unittest.TestCase):
    # 認証されたユーザーの初回発話において、過去ログが存在しないため要約や長期記憶のデータベースクエリ取得処理がスキップされ、適切に記憶抽出とコンテキスト生成が行われることを検証します。
    # Verify that the first turn of an authenticated user skips room summary and long-term memory queries (since they are empty), and correctly extracts facts and builds the prompt.
    def test_authenticated_first_turn_skips_empty_room_context_queries(self):
        user_message = "【タスク】レビュー\n【状況・作業環境】A&B"
        saved_messages = []
        history_query_message_counts = []
        captured_context = {}

        # リクエスト内のJSON辞書取得をシミュレート
        # Simulate requiring a JSON dictionary from the request
        async def require_json_dict(request):
            return await request.json(), None

        # ペイロードのバリデーションをシミュレート
        # Simulate validating the payload model
        def validate_payload_model(data, model_cls, **_kwargs):
            return model_cls(**data), None

        # JSONResponseレスポンスヘルパー
        # Helper to return a JSONResponse
        def jsonify(payload, status_code=200):
            return JSONResponse(payload, status_code=status_code)

        # メッセージのDB保存処理を疑似的に行う
        # Mock saving user and assistant messages to the DB
        def save_message_to_db(room_id, message, sender, attached_file_names=None, parent_id=None):
            saved_messages.append(
                {
                    "room_id": room_id,
                    "message": message,
                    "sender": sender,
                    "parent_id": parent_id,
                    "attached_file_names": attached_file_names,
                }
            )
            return len(saved_messages)

        # チャット履歴取得を疑似的に行う（メッセージ数計測付き）
        # Mock fetching chat history and log the message count
        def get_chat_room_messages(room_id):
            history_query_message_counts.append(len(saved_messages))
            return [
                {
                    "role": entry["sender"],
                    "content": entry["message"],
                }
                for entry in saved_messages
                if entry["room_id"] == room_id
            ]

        # プロンプト用コンテキストメッセージ構築をフック
        # Hook the prompt building to capture context variables
        def build_context_messages(**kwargs):
            captured_context.update(kwargs)
            return kwargs["recent_messages"]

        # 依存関係モックオブジェクトの作成
        # Create mocked dependency container for the chat post usecase
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
            validate_guest_room_access=Mock(),
            resolve_authenticated_room_target=Mock(return_value=("normal", None, None)),
            ensure_ephemeral_room=Mock(),
            get_temporary_user_store_key=Mock(return_value="tmp:user:42"),
            ephemeral_store=SimpleNamespace(
                append_message=Mock(),
                get_messages=Mock(return_value=[]),
            ),
            save_message_to_db=save_message_to_db,
            get_active_leaf_id=Mock(return_value=None),
            get_chat_room_messages=get_chat_room_messages,
            normalize_messages_for_llm=lambda messages: [
                {
                    "role": item["role"],
                    "content": str(item["content"]).replace("<br>", "\n").replace("&amp;", "&"),
                }
                for item in messages
            ],
            find_latest_task_launch_request=Mock(return_value=None),
            load_task_prompt_data=Mock(),
            build_task_prompt=Mock(return_value=None),
            get_user_by_id=Mock(return_value={}),
            build_user_profile_prompt=Mock(return_value=None),
            get_room_summary=Mock(return_value={"summary": "should not load"}),
            list_room_memory_facts=Mock(return_value=["should not load"]),
            remember_facts_from_message=Mock(return_value=["remembered fact"]),
            rename_chat_room_if_current_title_in=Mock(return_value=False),
            build_context_messages=build_context_messages,
            build_base_system_prompt=Mock(return_value="system"),
            build_generation_key=Mock(return_value="user:42:room-1"),
            has_active_generation=Mock(return_value=False),
            consume_llm_daily_quota=Mock(return_value=(True, 1, 300)),
            cleanup_failed_room_without_assistant_response=Mock(),
            get_seconds_until_daily_reset=Mock(return_value=60),
            is_streaming_model=Mock(return_value=False),
            start_generation_job=Mock(),
            build_llm_stream_response=Mock(),
            iter_llm_stream_events=Mock(),
            get_llm_response=Mock(return_value="assistant reply"),
            is_retryable_llm_error=Mock(return_value=False),
            rebuild_room_summary=Mock(),
            get_session_id=Mock(return_value="sid-1"),
            logger=Mock(),
        )
        use_case = ChatPostUseCase(deps, default_model="test-model")
        request = build_request(
            method="POST",
            path="/api/chat",
            json_body={
                "message": user_message,
                "chat_room_id": "room-1",
                "model": "test-model",
            },
            session={"user_id": 42},
        )

        # ウェブ検索拡張や自動タイトル生成処理をモック
        # Mock web search augmentation and automatic room renaming/titling
        with (
            patch(
                "services.chat_use_case.maybe_augment_messages_with_web_search",
                side_effect=lambda messages, _model: SimpleNamespace(messages=messages, result=None),
            ),
            patch("services.chat_use_case.maybe_auto_title_chat_room", return_value=None),
        ):
            response = asyncio.run(
                use_case.execute(
                    request,
                    auth_limit_service=object(),
                    llm_daily_limit_service=object(),
                    chat_generation_service=object(),
                )
            )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload, {"response": "assistant reply"})
        self.assertEqual(history_query_message_counts, [2])
        deps.get_room_summary.assert_not_called()
        deps.list_room_memory_facts.assert_not_called()
        deps.remember_facts_from_message.assert_called_once_with(
            "room-1",
            42,
            user_message,
            source_message_id=1,
        )
        self.assertEqual(
            captured_context["recent_messages"],
            [{"role": "user", "content": user_message}],
        )
        self.assertEqual(captured_context["memory_facts"], ["remembered fact"])


if __name__ == "__main__":
    unittest.main()
