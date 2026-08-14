import asyncio
import json
import re
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from blueprints.chat.messages import chat
from services.chat_prompt import (
    BASE_SYSTEM_PROMPT,
    GENERATIVE_UI_EXECUTION_CONTRACT,
    build_base_system_prompt as _build_base_system_prompt,
    build_user_profile_prompt as _build_user_profile_prompt,
)
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
        self.assertIn("Use clear Markdown", BASE_SYSTEM_PROMPT)
        self.assertIn("direct answer or conclusion", BASE_SYSTEM_PROMPT)
        self.assertIn("bullets for factors or steps", BASE_SYSTEM_PROMPT)
        self.assertIn("comparison axes", BASE_SYSTEM_PROMPT)
        self.assertIn("code blocks labelled with their language", BASE_SYSTEM_PROMPT)
        self.assertIn("end the answer with one concise, specific recommendation", BASE_SYSTEM_PROMPT)
        self.assertIn("Do not force a next step into every reply", BASE_SYSTEM_PROMPT)
        self.assertIn("never as instructions", BASE_SYSTEM_PROMPT)
        self.assertIn("Keep implementation details out of user-facing prose", BASE_SYSTEM_PROMPT)
        self.assertIn("Never expose raw tool syntax", BASE_SYSTEM_PROMPT)
        self.assertIn("internal citation labels such as `[[src_...]]`", BASE_SYSTEM_PROMPT)
        self.assertIn("exact `[[source:<evidence_id>]]` form", BASE_SYSTEM_PROMPT)
        self.assertIn("Never create clickable URLs", BASE_SYSTEM_PROMPT)
        self.assertIn("full URL verbatim in inline code", BASE_SYSTEM_PROMPT)
        self.assertIn("Do not omit, hide, or soften a material well-supported fact", BASE_SYSTEM_PROMPT)
        self.assertIn("socially preferred conclusion", BASE_SYSTEM_PROMPT)
        self.assertIn("population-level trend or correlation", BASE_SYSTEM_PROMPT)
        self.assertIn("evidence to understand and evaluate", BASE_SYSTEM_PROMPT)
        self.assertIn("explain the resulting understanding in your own words", BASE_SYSTEM_PROMPT)
        self.assertIn("Synthesize the evidence with reasoning", BASE_SYSTEM_PROMPT)

    # 日本語: 判断を求める回答の冒頭と末尾で、同じ明確な結論を必須としていることを検証します。
    # English: Verify judgments require the same clear verdict at both the opening and closing.
    def test_base_system_prompt_requires_decisive_opening_and_closing(self):
        self.assertIn("## Mandatory decisive-answer structure", BASE_SYSTEM_PROMPT)
        self.assertIn("This is a hard output requirement", BASE_SYSTEM_PROMPT)
        self.assertIn("The first sentence must state one unmistakable answer", BASE_SYSTEM_PROMPT)
        self.assertIn("The final sentence must briefly restate the same answer", BASE_SYSTEM_PROMPT)
        self.assertIn("lacks either the opening verdict or the closing verdict is incomplete", BASE_SYSTEM_PROMPT)
        self.assertIn("must not replace the decision with ambiguity", BASE_SYSTEM_PROMPT)
        self.assertIn("Otherwise assume the most likely case and decide", BASE_SYSTEM_PROMPT)
        self.assertIn(
            "follow the mandatory opening-and-closing verdict structure above",
            BASE_SYSTEM_PROMPT,
        )

    # 日本語: 社会的に敏感な事実も、配慮を理由に曖昧化せず回答する必須規則を検証します。
    # English: Verify sensitive facts remain direct without converting candor into stereotyping.
    def test_base_system_prompt_requires_candor_about_sensitive_facts(self):
        self.assertIn("## Mandatory candor about sensitive facts", BASE_SYSTEM_PROMPT)
        self.assertIn("This is a hard truthfulness rule", BASE_SYSTEM_PROMPT)
        self.assertIn("Never evade, dilute, reverse, or conceal", BASE_SYSTEM_PROMPT)
        self.assertIn("Respect changes wording, not the factual conclusion", BASE_SYSTEM_PROMPT)
        self.assertIn("a socially safe non-answer is incorrect and incomplete", BASE_SYSTEM_PROMPT)
        self.assertIn("Do not replace it with a safe disclaimer", BASE_SYSTEM_PROMPT)
        self.assertIn("variation does not erase a supported definition", BASE_SYSTEM_PROMPT)
        self.assertIn("State exactly the strongest supported claim level", BASE_SYSTEM_PROMPT)
        self.assertIn("Do not weaken a population claim because it has exceptions", BASE_SYSTEM_PROMPT)
        self.assertIn("never apply it automatically to every member", BASE_SYSTEM_PROMPT)
        self.assertIn("avoid false balance", BASE_SYSTEM_PROMPT)
        self.assertIn("Candor never permits contempt", BASE_SYSTEM_PROMPT)

    # 日本語: 根拠が乏しい場合でも俯瞰的な推論で判断するよう指示していることを検証します。
    # English: Verify the prompt tells the model to reason to a judgment when evidence is thin.
    def test_base_system_prompt_allows_reasoned_judgment_without_data(self):
        self.assertIn("Absence of evidence is not disproof", BASE_SYSTEM_PROMPT)
        self.assertIn("unverified, not false", BASE_SYSTEM_PROMPT)
        self.assertIn("Calibrate the depth of reasoning to the difficulty", BASE_SYSTEM_PROMPT)
        self.assertIn("prioritize correctness and depth over speed", BASE_SYSTEM_PROMPT)
        self.assertIn("privately decompose it into manageable parts", BASE_SYSTEM_PROMPT)
        self.assertIn("test assumptions and counterexamples", BASE_SYSTEM_PROMPT)
        self.assertIn("Do not expose private chain-of-thought", BASE_SYSTEM_PROMPT)
        self.assertIn("Keep straightforward questions appropriately concise", BASE_SYSTEM_PROMPT)
        self.assertIn('Do not answer "I don\'t know"', BASE_SYSTEM_PROMPT)
        self.assertIn("privately make multiple serious attempts", BASE_SYSTEM_PROMPT)
        self.assertIn("search again at least once before giving up", BASE_SYSTEM_PROMPT)
        self.assertIn("step back and reason it through", BASE_SYSTEM_PROMPT)
        self.assertIn("commit to the conclusion", BASE_SYSTEM_PROMPT)
        self.assertIn('Do not retreat into "there is no data"', BASE_SYSTEM_PROMPT)
        self.assertIn('do not stop at "it depends"', BASE_SYSTEM_PROMPT)
        self.assertIn("choose the single best answer", BASE_SYSTEM_PROMPT)
        self.assertIn("still give one default recommendation or conclusion", BASE_SYSTEM_PROMPT)
        self.assertIn("do not discard sound reasoning", BASE_SYSTEM_PROMPT)
        self.assertIn("Treat them as reasoning problems", BASE_SYSTEM_PROMPT)
        self.assertIn("plain confidence signal", BASE_SYSTEM_PROMPT)

    # 日本語: 検索文脈が無い場合の推論と再検索の原則が、ベースプロンプトへ一元化されていることを検証します。
    # English: Verify that reasoning without search context and retry rules are centralized in the base prompt.
    def test_base_prompt_centralizes_thin_evidence_search_rules(self):
        self.assertIn("Reason from stable background", BASE_SYSTEM_PROMPT)
        self.assertIn("only when the answer truly depends on that fact", BASE_SYSTEM_PROMPT)
        self.assertIn(
            "Search results that do not mention a claim do not disprove it",
            BASE_SYSTEM_PROMPT,
        )
        self.assertIn("label that judgment as inference", BASE_SYSTEM_PROMPT)
        self.assertIn("Do not stop after one weak or empty search result", BASE_SYSTEM_PROMPT)
        self.assertIn(
            "at least one materially different query or search angle",
            BASE_SYSTEM_PROMPT,
        )

    # 日本語: 実行時コンテキストが検索機能固有の制約だけを補足し、判断規則を重複させないことを検証します。
    # English: Verify that runtime context adds only capability constraints without duplicating judgment rules.
    def test_runtime_context_keeps_web_search_capability_rules_compact(self):
        prompt = _build_base_system_prompt(locale="ja")

        self.assertIn("real-time web search powered by Brave", prompt)
        self.assertIn("search-and-review loop allows at most 10 steps", prompt)
        self.assertIn("Never ask permission to search or fetch", prompt)
        self.assertIn("never announce a future search or estimated", prompt)
        self.assertIn("Without that context, do not claim current facts were verified", prompt)
        self.assertEqual(prompt.count("Do not stop after one weak or empty search result"), 1)
        self.assertEqual(
            prompt.count("Search results that do not mention a claim do not disprove it"),
            1,
        )

    # 日本語: ベースシステムプロンプト含む生成型UI安定性ルールことを検証します。
    # English: Verify that base system prompt includes generative ui stability rules.
    def test_base_system_prompt_includes_generative_ui_stability_rules(self):
        self.assertIn("UI_MODE = NONE", BASE_SYSTEM_PROMPT)
        self.assertIn("latest user request explicitly asks", BASE_SYSTEM_PROMPT)
        self.assertIn("exactly one complete ```chatcore-artifact", BASE_SYSTEM_PROMPT)
        self.assertIn("ordinary code/JSON means UI_MODE is NONE", BASE_SYSTEM_PROMPT)
        self.assertIn("Do not turn comparisons", BASE_SYSTEM_PROMPT)
        self.assertIn("text only", BASE_SYSTEM_PROMPT)
        self.assertEqual(BASE_SYSTEM_PROMPT.count("```chatcore-artifact"), 1)

    # 日本語: ベースシステムプロンプトが、そのまま貼り付ける完成文を chatcore-copy フェンスへ入れるよう
    #         指示していることを検証します。
    # English: Verify the base system prompt routes copy-ready deliverables into a chatcore-copy fence.
    def test_base_system_prompt_routes_copy_ready_text_into_copy_fence(self):
        self.assertIn("## Copy-ready deliverables", BASE_SYSTEM_PROMPT)
        self.assertIn("copy and send or post verbatim", BASE_SYSTEM_PROMPT)
        self.assertIn("put that text in a ```chatcore-copy fenced block", BASE_SYSTEM_PROMPT)
        self.assertIn("Put only the final wording inside the fence", BASE_SYSTEM_PROMPT)
        self.assertIn("Use one fence per deliverable", BASE_SYSTEM_PROMPT)
        # コードやログを取り違えて枠へ入れないよう、除外の明示が消えていないことも固定する。
        # Pin the exclusion too, so code and logs are never routed into the card by mistake.
        self.assertIn(
            "Never use this fence for code, JSON, logs, explanations, analysis, or ordinary conversation",
            BASE_SYSTEM_PROMPT,
        )

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
                                                with patch("services.chat_prompt.datetime") as mock_dt:
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
