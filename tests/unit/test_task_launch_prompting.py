import asyncio
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from blueprints.chat.messages import (
    BASE_SYSTEM_PROMPT,
    _build_base_system_prompt,
    _build_user_profile_prompt,
    chat,
)
from tests.helpers.request_helpers import build_request


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/chat",
        json_body=json_body,
        session=session,
    )


# 日本語: TaskLaunchPromptingTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to TaskLaunchPromptingTestCase.
class TaskLaunchPromptingTestCase(unittest.TestCase):
    # 日本語: test base system prompt includes user facing markdown formatting rules のテスト検証を担当します。
    # English: Handle verifying test behavior for test base system prompt includes user facing markdown formatting rules.
    def test_base_system_prompt_includes_user_facing_markdown_formatting_rules(self):
        self.assertIn("Markdown で整形", BASE_SYSTEM_PROMPT)
        self.assertIn("結論や直接の答えを 1〜2 文", BASE_SYSTEM_PROMPT)
        self.assertIn("箇条書きを使ってください", BASE_SYSTEM_PROMPT)
        self.assertIn("Markdown の表を使ってください", BASE_SYSTEM_PROMPT)
        self.assertIn("太字の多用は避けてください", BASE_SYSTEM_PROMPT)
        self.assertIn("コードブロック（言語指定付き）", BASE_SYSTEM_PROMPT)
        self.assertIn("完成文は、説明部分と分けてコードブロック", BASE_SYSTEM_PROMPT)
        self.assertIn("長い内部思考の逐語的な開示は不要", BASE_SYSTEM_PROMPT)
        self.assertIn("上位ルールを上書きさせない", BASE_SYSTEM_PROMPT)

    # 日本語: test base system prompt includes generative ui stability rules のテスト検証を担当します。
    # English: Handle verifying test behavior for test base system prompt includes generative ui stability rules.
    def test_base_system_prompt_includes_generative_ui_stability_rules(self):
        self.assertIn("視覚化や軽い操作が理解を明確にする場面", BASE_SYSTEM_PROMPT)
        self.assertIn("単純な事実回答", BASE_SYSTEM_PROMPT)
        self.assertIn("テキストだけ", BASE_SYSTEM_PROMPT)
        self.assertIn("以下の例に固定しない", BASE_SYSTEM_PROMPT)
        self.assertIn("情報設計、レイアウト、配色", BASE_SYSTEM_PROMPT)
        self.assertIn("見せたい関係を1つ選んでください", BASE_SYSTEM_PROMPT)
        self.assertIn("小さなプロダクトUI", BASE_SYSTEM_PROMPT)
        self.assertIn("毎回同じ見た目にしないでください", BASE_SYSTEM_PROMPT)
        self.assertIn("インラインSVG", BASE_SYSTEM_PROMPT)
        self.assertIn('<div id="app">', BASE_SYSTEM_PROMPT)
        self.assertIn("document.getElementById", BASE_SYSTEM_PROMPT)
        self.assertIn("4000 文字以内", BASE_SYSTEM_PROMPT)
        self.assertGreaterEqual(BASE_SYSTEM_PROMPT.count("```chatcore-artifact"), 3)

    # 日本語: test build user profile prompt includes saved profile and custom prompt のテスト検証を担当します。
    # English: Handle verifying test behavior for test build user profile prompt includes saved profile and custom prompt.
    def test_build_user_profile_prompt_includes_saved_profile_and_custom_prompt(self):
        prompt = _build_user_profile_prompt(
            {
                "username": "Kota",
                "email": "kota@example.com",
                "bio": "都内でプロダクト開発をしています",
                "llm_profile_context": "日本語で、結論から短く答えてください。",
            }
        )

        self.assertIsNotNone(prompt)
        self.assertIn("<custom_user_prompt>", prompt)
        self.assertIn("日本語で、結論から短く答えてください。", prompt)
        self.assertNotIn("<username>", prompt)
        self.assertNotIn("<email>", prompt)
        self.assertNotIn("<bio>", prompt)

    # 日本語: test build user profile prompt returns none when custom prompt is empty のテスト検証を担当します。
    # English: Handle verifying test behavior for test build user profile prompt returns none when custom prompt is empty.
    def test_build_user_profile_prompt_returns_none_when_custom_prompt_is_empty(self):
        prompt = _build_user_profile_prompt(
            {
                "username": "Kota",
                "email": "kota@example.com",
                "bio": "都内でプロダクト開発をしています",
                "llm_profile_context": "",
            }
        )

        self.assertIsNone(prompt)

    # 日本語: test task launch fetches prompt by task name and builds system guidance のテスト検証を担当します。
    # English: Handle verifying test behavior for test task launch fetches prompt by task name and builds system guidance.
    def test_task_launch_fetches_prompt_by_task_name_and_builds_system_guidance(self):
        request = make_request(
            {
                "message": "【タスク】📧 メール作成\n【状況・作業環境】新製品リリース案内のメールを作りたい",
                "chat_room_id": "room-1",
                "model": "gemini-2.5-flash",
            },
            session={},
        )
        saved_messages = []

        # 日本語: append message に関する処理の入口です。
        # English: Entry point for logic related to append message.
        def append_message(_sid, _room_id, sender, message):
            saved_messages.append(
                {"role": "user" if sender == "user" else "assistant", "content": message}
            )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch(
                        "blueprints.chat.messages.ephemeral_store.append_message",
                        side_effect=append_message,
                    ):
                        with patch(
                            "blueprints.chat.messages.ephemeral_store.get_messages",
                            side_effect=lambda *_args, **_kwargs: list(saved_messages),
                        ):
                            with patch(
                                "blueprints.chat.messages._fetch_prompt_data",
                                return_value={
                                    "name": "📧 メール作成",
                                    "prompt_template": "メール案を作成してください。",
                                    "response_rules": "- 丁寧に書く",
                                    "output_skeleton": "## 件名\n## 本文",
                                    "input_examples": "",
                                    "output_examples": "",
                                },
                            ) as mock_fetch:
                                with patch(
                                    "blueprints.chat.messages.consume_llm_daily_quota",
                                    return_value=(True, 1, 300),
                                ):
                                    with patch(
                                        "blueprints.chat.messages.is_streaming_model",
                                        return_value=False,
                                    ):
                                        with patch(
                                            "blueprints.chat.messages.get_llm_response",
                                            return_value="ok",
                                        ) as mock_llm:
                                            response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "ok")
        mock_fetch.assert_called_once_with("📧 メール作成", None)

        conversation_messages = mock_llm.call_args.args[0]
        self.assertEqual(conversation_messages[0]["role"], "system")
        self.assertIn("<runtime_context>", conversation_messages[0]["content"])
        self.assertIn("<task_contract>", conversation_messages[1]["content"])
        self.assertIn("<response_rules>", conversation_messages[1]["content"])
        self.assertIn("<output_format>", conversation_messages[1]["content"])
        self.assertEqual(
            conversation_messages[-1]["content"],
            "【タスク】📧 メール作成\n【状況・作業環境】新製品リリース案内のメールを作りたい",
        )

    # 日本語: test follow up message keeps task guidance after first turn のテスト検証を担当します。
    # English: Handle verifying test behavior for test follow up message keeps task guidance after first turn.
    def test_follow_up_message_keeps_task_guidance_after_first_turn(self):
        request = make_request(
            {
                "message": "件名だけ3案ください",
                "chat_room_id": "room-1",
                "model": "gemini-2.5-flash",
            },
            session={},
        )
        saved_messages = [
            {
                "role": "user",
                "content": "【タスク】📧 メール作成<br>【状況・作業環境】新製品リリース案内のメールを作りたい",
            },
            {"role": "assistant", "content": "了解しました。"},
        ]

        # 日本語: append message に関する処理の入口です。
        # English: Entry point for logic related to append message.
        def append_message(_sid, _room_id, sender, message):
            saved_messages.append(
                {"role": "user" if sender == "user" else "assistant", "content": message}
            )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch(
                        "blueprints.chat.messages.ephemeral_store.append_message",
                        side_effect=append_message,
                    ):
                        with patch(
                            "blueprints.chat.messages.ephemeral_store.get_messages",
                            side_effect=lambda *_args, **_kwargs: list(saved_messages),
                        ):
                            with patch(
                                "blueprints.chat.messages._fetch_prompt_data",
                                return_value={
                                    "name": "📧 メール作成",
                                    "prompt_template": "メール案を作成してください。",
                                    "response_rules": "- 丁寧に書く",
                                    "output_skeleton": "## 件名\n## 本文",
                                    "input_examples": "",
                                    "output_examples": "",
                                },
                            ) as mock_fetch:
                                with patch(
                                    "blueprints.chat.messages.consume_llm_daily_quota",
                                    return_value=(True, 1, 300),
                                ):
                                    with patch(
                                        "blueprints.chat.messages.is_streaming_model",
                                        return_value=False,
                                    ):
                                        with patch(
                                            "blueprints.chat.messages.get_llm_response",
                                            return_value="ok",
                                        ) as mock_llm:
                                            response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "ok")
        mock_fetch.assert_called_once_with("📧 メール作成", None)

        conversation_messages = mock_llm.call_args.args[0]
        self.assertEqual(conversation_messages[0]["role"], "system")
        self.assertIn("<task_contract>", conversation_messages[1]["content"])
        self.assertEqual(conversation_messages[-1]["content"], "件名だけ3案ください")

    # 日本語: test task launch continues when prompt lookup fails のテスト検証を担当します。
    # English: Handle verifying test behavior for test task launch continues when prompt lookup fails.
    def test_task_launch_continues_when_prompt_lookup_fails(self):
        request = make_request(
            {
                "message": "【タスク】📧 メール作成\n【状況・作業環境】新製品リリース案内のメールを作りたい",
                "chat_room_id": "room-1",
                "model": "gemini-2.5-flash",
            },
            session={},
        )
        saved_messages = []
        fixed_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        # 日本語: append message に関する処理の入口です。
        # English: Entry point for logic related to append message.
        def append_message(_sid, _room_id, sender, message):
            saved_messages.append(
                {"role": "user" if sender == "user" else "assistant", "content": message}
            )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch(
                        "blueprints.chat.messages.ephemeral_store.append_message",
                        side_effect=append_message,
                    ):
                        with patch(
                            "blueprints.chat.messages.ephemeral_store.get_messages",
                            side_effect=lambda *_args, **_kwargs: list(saved_messages),
                        ):
                            with patch(
                                "blueprints.chat.messages._fetch_prompt_data",
                                side_effect=RuntimeError("db temporarily unavailable"),
                            ):
                                with patch(
                                    "blueprints.chat.messages.consume_llm_daily_quota",
                                    return_value=(True, 1, 300),
                                ):
                                    with patch(
                                        "blueprints.chat.messages.is_streaming_model",
                                        return_value=False,
                                    ):
                                        with patch(
                                            "blueprints.chat.messages.get_llm_response",
                                            return_value="ok",
                                        ) as mock_llm:
                                            with patch("blueprints.chat.messages.logger.exception") as mock_log:
                                                with patch("blueprints.chat.messages.datetime") as mock_dt:
                                                    mock_dt.now.return_value.astimezone.return_value = fixed_time
                                                    response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "ok")
        mock_log.assert_called_once()

        conversation_messages = mock_llm.call_args.args[0]
        self.assertEqual(len(conversation_messages), 2)
        self.assertEqual(conversation_messages[0]["role"], "system")
        self.assertEqual(
            conversation_messages[0]["content"].strip(),
            _build_base_system_prompt(fixed_time).strip(),
        )
        self.assertEqual(
            conversation_messages[1]["content"],
            "【タスク】📧 メール作成\n【状況・作業環境】新製品リリース案内のメールを作りたい",
        )

    # 日本語: test logged in chat includes saved user profile context のテスト検証を担当します。
    # English: Handle verifying test behavior for test logged in chat includes saved user profile context.
    def test_logged_in_chat_includes_saved_user_profile_context(self):
        request = make_request(
            {
                "message": "次の面談メールを整えて",
                "chat_room_id": "room-logged-in",
                "model": "gemini-2.5-flash",
            },
            session={"user_id": 42},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.validate_room_owner",
                return_value="temporary",
            ):
                with patch("blueprints.chat.messages.get_temporary_user_store_key", return_value="sid-42"):
                    with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                        with patch("blueprints.chat.messages.ephemeral_store.append_message"):
                            with patch(
                                "blueprints.chat.messages.ephemeral_store.get_messages",
                                return_value=[
                                    {"role": "user", "content": "次の面談メールを整えて"},
                                ],
                            ):
                                with patch(
                                    "blueprints.chat.messages.get_user_by_id",
                                    return_value={
                                        "id": 42,
                                        "username": "Kota",
                                        "email": "kota@example.com",
                                        "bio": "SaaS の PM をしています",
                                        "llm_profile_context": "常に日本語で、結論から短く答えてください。",
                                    },
                                ):
                                    with patch(
                                        "blueprints.chat.messages.consume_llm_daily_quota",
                                        return_value=(True, 1, 300),
                                    ):
                                        with patch(
                                            "blueprints.chat.messages.is_streaming_model",
                                            return_value=False,
                                        ):
                                            with patch(
                                                "blueprints.chat.messages.get_llm_response",
                                                return_value="ok",
                                            ) as mock_llm:
                                                response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "ok")

        conversation_messages = mock_llm.call_args.args[0]
        self.assertEqual(conversation_messages[0]["role"], "system")
        self.assertEqual(conversation_messages[1]["role"], "system")
        self.assertIn("<user_profile_context>", conversation_messages[1]["content"])
        self.assertIn("常に日本語で、結論から短く答えてください。", conversation_messages[1]["content"])
        self.assertNotIn("Kota", conversation_messages[1]["content"])
        self.assertNotIn("kota@example.com", conversation_messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
