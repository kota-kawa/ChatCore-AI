import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.messages import (
    BASE_SYSTEM_PROMPT,
    _build_base_system_prompt,
    chat,
)
from tests.helpers.request_helpers import build_request


def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/chat",
        json_body=json_body,
        session=session,
    )


class TaskLaunchPromptingTestCase(unittest.TestCase):
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

        def append_message(_sid, _room_id, sender, message):
            saved_messages.append(
                {"role": "user" if sender == "user" else "assistant", "content": message}
            )

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

        def append_message(_sid, _room_id, sender, message):
            saved_messages.append(
                {"role": "user" if sender == "user" else "assistant", "content": message}
            )

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

        def append_message(_sid, _room_id, sender, message):
            saved_messages.append(
                {"role": "user" if sender == "user" else "assistant", "content": message}
            )

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
            _build_base_system_prompt().strip(),
        )
        self.assertEqual(
            conversation_messages[1]["content"],
            "【タスク】📧 メール作成\n【状況・作業環境】新製品リリース案内のメールを作りたい",
        )


if __name__ == "__main__":
    unittest.main()
