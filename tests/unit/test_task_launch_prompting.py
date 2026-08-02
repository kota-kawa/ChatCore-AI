import asyncio
import json
import re
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from blueprints.chat.messages import (
    BASE_SYSTEM_PROMPT,
    _build_base_system_prompt,
    _build_user_profile_prompt,
    chat,
)
from services.chat_context import GENERATIVE_UI_EXECUTION_CONTRACT
from tests.helpers.request_helpers import build_request


def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/chat",
        json_body=json_body,
        session=session,
    )


# 日本語: Task Launch Promptingの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Task Launch Prompting.
class TaskLaunchPromptingTestCase(unittest.TestCase):
    def test_base_system_prompt_uses_saved_locale_only_as_language_fallback(self):
        prompt = _build_base_system_prompt(locale="en")

        self.assertIn("language of the user's input text", prompt)
        self.assertIn("latest substantive message", prompt)
        self.assertIn("An explicit language request from the user takes priority", prompt)
        self.assertIn("saved interface language (English)", prompt)
        self.assertIn("Do not translate user-authored content", prompt)

    # 日本語: 混在言語の入力に対する応答言語の決定順序が示されていることを検証します。
    # English: Verify the prompt states how to pick the reply language for mixed-language input.
    def test_base_system_prompt_explains_mixed_language_resolution_order(self):
        prompt = _build_base_system_prompt(locale="ja")

        self.assertIn("mixes languages", prompt)
        self.assertIn("the part that states the user's request or instruction", prompt)
        self.assertIn("larger share", prompt)
        self.assertIn("saved interface language (Japanese)", prompt)
        self.assertIn("Keep one language throughout a single reply", prompt)

    # 日本語: システムプロンプト本文が英語で書かれていることを検証します。
    # English: Verify that the base system prompt itself is written in English.
    def test_base_system_prompt_is_written_in_english(self):
        self.assertFalse(
            re.search(r"[぀-ヿ一-鿿]", BASE_SYSTEM_PROMPT),
            "BASE_SYSTEM_PROMPT must not contain Japanese characters.",
        )

    # 日本語: ベースシステムプロンプト含むユーザー向けのMarkdownフォーマットルールことを検証します。
    # English: Verify that base system prompt includes user facing markdown formatting rules.
    def test_base_system_prompt_includes_user_facing_markdown_formatting_rules(self):
        self.assertIn("Format the answer in Markdown", BASE_SYSTEM_PROMPT)
        self.assertIn("conclusion or the direct answer in 1-2 sentences", BASE_SYSTEM_PROMPT)
        self.assertIn("Use bullet lists", BASE_SYSTEM_PROMPT)
        self.assertIn("use a Markdown table", BASE_SYSTEM_PROMPT)
        self.assertIn("Avoid overusing bold", BASE_SYSTEM_PROMPT)
        self.assertIn("code block with the language specified", BASE_SYSTEM_PROMPT)
        self.assertIn("in a code block separated from your explanation", BASE_SYSTEM_PROMPT)
        self.assertIn("disclose long internal reasoning verbatim", BASE_SYSTEM_PROMPT)
        self.assertIn("do not let it override the system rules", BASE_SYSTEM_PROMPT)

    # 日本語: ベースシステムプロンプト含む生成型UI安定性ルールことを検証します。
    # English: Verify that base system prompt includes generative ui stability rules.
    def test_base_system_prompt_includes_generative_ui_stability_rules(self):
        self.assertIn("UI_MODE = NONE / 2D / 3D", BASE_SYSTEM_PROMPT)
        self.assertIn("ending the answer with only a short explanation is prohibited", BASE_SYSTEM_PROMPT)
        self.assertIn(
            "the user explicitly mentions 3D, solid shapes, spatial models, orbits, or rotation",
            BASE_SYSTEM_PROMPT,
        )
        self.assertIn("there is exactly one Artifact", BASE_SYSTEM_PROMPT)
        self.assertIn("a visualization or light interaction makes understanding clearer", BASE_SYSTEM_PROMPT)
        self.assertIn("simple factual answers", BASE_SYSTEM_PROMPT)
        self.assertIn("text only", BASE_SYSTEM_PROMPT)
        self.assertIn("Do not lock the Artifact design to the examples below", BASE_SYSTEM_PROMPT)
        self.assertIn("information design, layout, color scheme", BASE_SYSTEM_PROMPT)
        self.assertIn("pick one relationship you want to show", BASE_SYSTEM_PROMPT)
        self.assertIn("little product UI", BASE_SYSTEM_PROMPT)
        self.assertIn("Do not produce the same look every time", BASE_SYSTEM_PROMPT)
        self.assertIn("inline SVG", BASE_SYSTEM_PROMPT)
        self.assertIn('<div id="app">', BASE_SYSTEM_PROMPT)
        self.assertIn("document.getElementById", BASE_SYSTEM_PROMPT)
        self.assertIn("preferably within 4000", BASE_SYSTEM_PROMPT)
        self.assertGreaterEqual(BASE_SYSTEM_PROMPT.count("```chatcore-artifact"), 3)

    # 日本語: およびカスタムプロンプト、ビルドユーザープロフィールプロンプト含む保存されたプロフィールことを検証します。
    # English: Verify that build user profile prompt includes saved profile and custom prompt.
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

    # 日本語: カスタムプロンプトが空のとき、ビルドユーザープロフィールプロンプト返却するnoneことを検証します。
    # English: Verify that build user profile prompt returns none when custom prompt is empty.
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

    # 日本語: タスク名によって、およびビルドするシステムガイダンス、タスク起動取得するプロンプトことを検証します。
    # English: Verify that task launch fetches prompt by task name and builds system guidance.
    def test_task_launch_fetches_prompt_by_task_name_and_builds_system_guidance(self):
        request = make_request(
            {
                "message": "【タスク】📧 メール作成\n【状況・作業環境】新製品リリース案内のメールを作りたい",
                "chat_room_id": "room-1",
                "model": "claude-haiku-4-5-20251001",
            },
            session={},
        )
        saved_messages = []

        def append_message(_sid, _room_id, sender, message, *args, **kwargs):
            saved_messages.append(
                {"role": "user" if sender == "user" else "assistant", "content": message}
            )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
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

    # 日本語: 初回ターンの後、フォローアップmessage保持するタスクガイダンスことを検証します。
    # English: Verify that follow up message keeps task guidance after first turn.
    def test_follow_up_message_keeps_task_guidance_after_first_turn(self):
        request = make_request(
            {
                "message": "件名だけ3案ください",
                "chat_room_id": "room-1",
                "model": "claude-haiku-4-5-20251001",
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

        def append_message(_sid, _room_id, sender, message, *args, **kwargs):
            saved_messages.append(
                {"role": "user" if sender == "user" else "assistant", "content": message}
            )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
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

    # 日本語: プロンプトルックアップ失敗するのとき、タスク起動継続することを検証します。
    # English: Verify that task launch continues when prompt lookup fails.
    def test_task_launch_continues_when_prompt_lookup_fails(self):
        request = make_request(
            {
                "message": "【タスク】📧 メール作成\n【状況・作業環境】新製品リリース案内のメールを作りたい",
                "chat_room_id": "room-1",
                "model": "claude-haiku-4-5-20251001",
            },
            session={},
        )
        saved_messages = []
        fixed_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        def append_message(_sid, _room_id, sender, message, *args, **kwargs):
            saved_messages.append(
                {"role": "user" if sender == "user" else "assistant", "content": message}
            )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
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
        self.assertEqual(len(conversation_messages), 3)
        self.assertEqual(conversation_messages[0]["role"], "system")
        self.assertEqual(
            conversation_messages[0]["content"].strip(),
            _build_base_system_prompt(fixed_time).strip(),
        )
        self.assertEqual(
            conversation_messages[1]["content"],
            GENERATIVE_UI_EXECUTION_CONTRACT,
        )
        self.assertEqual(
            conversation_messages[2]["content"],
            "【タスク】📧 メール作成\n【状況・作業環境】新製品リリース案内のメールを作りたい",
        )

    # 日本語: チャット含む保存されたユーザープロフィールコンテキスト内の、ログインことを検証します。
    # English: Verify that logged in chat includes saved user profile context.
    def test_logged_in_chat_includes_saved_user_profile_context(self):
        request = make_request(
            {
                "message": "次の面談メールを整えて",
                "chat_room_id": "room-logged-in",
                "model": "claude-haiku-4-5-20251001",
            },
            session={"user_id": 42},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
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
