"""会話から文脈の候補を取り出す context_vault_extraction（固定モデル、閾値、原文の一致、入力長、
背景実行）を検証するテスト。

Tests context_vault_extraction, which pulls context candidates out of a chat: fixed model, thresholds,
verbatim evidence, input bounds and background execution.
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.context_vault_extraction import (
    MAX_EXTRACTION_ASSISTANT_RESPONSE_CHARS,
    MAX_EXTRACTION_USER_MESSAGE_CHARS,
    SENSITIVE_CATEGORY_DESCRIPTIONS,
    build_extraction_system_prompt,
    extract_context_candidates,
    schedule_context_extraction,
)
from services.llm import GPT_6_LUNA_MODEL


# 日本語: LLM 呼び出しをモックし、抽出結果の採否と、背景実行時のエラー処理を確認します。
# English: Mock the LLM call and check which candidates are accepted, plus error handling in background runs.
class ContextVaultExtractionTestCase(unittest.TestCase):
    def test_extracts_only_high_value_high_confidence_non_secret_candidates_with_fixed_model(self):
        llm = Mock(
            return_value=json.dumps(
                {
                    "candidates": [
                        {
                            "fact_type": "preference",
                            "title": "Preferred editor",
                            "content": "The user prefers Vim.",
                            "evidence": "I always use Vim",
                            "importance": 80,
                            "confidence": 0.95,
                        },
                        {
                            "fact_type": "reference",
                            "title": "Temporary research topic",
                            "content": "The user asked about Google's job openings.",
                            "evidence": "I always use Vim",
                            "importance": 40,
                            "confidence": 0.99,
                        },
                        {
                            "fact_type": "reference",
                            "title": "API credential",
                            "content": "API key: sk-1234567890abcdefghijklmnop",
                            "evidence": "My API key is secret.",
                            "importance": 100,
                            "confidence": 0.99,
                        },
                    ]
                }
            )
        )

        candidates = extract_context_candidates(
            "I always use Vim. My API key is secret.",
            "I will remember that you like Vim.",
            llm_json_response=llm,
        )

        self.assertEqual(
            candidates,
            [
                {
                    "fact_type": "preference",
                    "title": "Preferred editor",
                    "content": "The user prefers Vim.",
                    "evidence": "I always use Vim",
                    "importance": 80,
                    "confidence": 0.95,
                }
            ],
        )
        messages, model = llm.call_args.args
        self.assertEqual(model, GPT_6_LUNA_MODEL)
        self.assertEqual(len(messages), 2)
        self.assertEqual(
            json.loads(messages[1]["content"])["user_message"],
            "I always use Vim. My API key is secret.",
        )
        self.assertEqual(
            json.loads(messages[1]["content"])["assistant_response"],
            "I will remember that you like Vim.",
        )
        prompt = build_extraction_system_prompt("ja")
        self.assertIn("majority of chat turns must produce no candidates", prompt)
        self.assertIn(
            "Do not turn a single question, search, mention, or pasted text into a personal interest",
            prompt,
        )
        self.assertIn("What are Google's current job openings?", prompt)
        self.assertIn("six months from now", prompt)

    def test_prompt_uses_user_message_language_and_rejects_momentary_curiosity(self):
        for locale in ("ja", "en"):
            with self.subTest(locale=locale):
                prompt = build_extraction_system_prompt(locale)
                self.assertIn(
                    "Write the whole reply in the language of the user's latest substantive message",
                    prompt,
                )
                self.assertIn(
                    "Never default to English because these instructions are in English.",
                    prompt,
                )
                self.assertIn("message is the text in user_message", prompt)
                self.assertIn("not the JSON wrapper, assistant_response, or these instructions", prompt)
                self.assertIn("interface language is only a fallback", prompt)
                self.assertIn("Unless user_message explicitly requests another output language", prompt)
                self.assertIn("English user_message requires English title and content", prompt)
                self.assertIn("Japanese user_message requires Japanese title and content", prompt)
                self.assertIn("must never be translated or rewritten", prompt)
                self.assertIn("Momentary curiosity is not personal context.", prompt)
                self.assertIn("気になって", prompt)
                self.assertIn("at most 300 characters", prompt)
                self.assertNotIn("{language_policy}", prompt)
                self.assertNotIn("{evidence_quote_chars}", prompt)

        self.assertIn("Japanese", build_extraction_system_prompt("ja"))
        self.assertIn("English", build_extraction_system_prompt("en"))

    def test_locale_reaches_the_extraction_prompt(self):
        llm = Mock(return_value='{"candidates": []}')

        extract_context_candidates("message", "response", locale="en", llm_json_response=llm)

        system_prompt = llm.call_args.args[0][0]["content"]
        self.assertEqual(system_prompt, build_extraction_system_prompt("en"))

    def test_rejects_candidates_below_durability_or_confidence_thresholds(self):
        llm = Mock(
            return_value=json.dumps(
                {
                    "candidates": [
                        {
                            "fact_type": "profile",
                            "title": "Possible location",
                            "content": "The user may live in Tokyo.",
                            "evidence": "What are Google's current job openings?",
                            "importance": 90,
                            "confidence": 0.89,
                        },
                        {
                            "fact_type": "reference",
                            "title": "Temporary research topic",
                            "content": "The user asked about Google's job openings.",
                            "evidence": "What are Google's current job openings?",
                            "importance": 79,
                            "confidence": 0.99,
                        },
                    ]
                }
            )
        )

        self.assertEqual(
            extract_context_candidates(
                "What are Google's current job openings?",
                "Here are the current openings.",
                llm_json_response=llm,
            ),
            [],
        )

    def test_rejects_candidates_without_a_verbatim_span_of_the_user_message(self):
        def candidate_with(evidence):
            return json.dumps(
                {
                    "candidates": [
                        {
                            "fact_type": "preference",
                            "title": "深海魚への関心",
                            "content": "ユーザーは深海魚に関心がある。",
                            "evidence": evidence,
                            "importance": 90,
                            "confidence": 0.95,
                        }
                    ]
                }
            )

        user_message = "深海魚って気になるんだけど、\nどんな種類がいるの？"
        unsupported = (
            "",
            "ユーザーは深海魚が好きだ",
            "深海魚が趣味です",
            "深海魚って気になる…どんな種類",
        )
        for evidence in unsupported:
            with self.subTest(evidence=evidence):
                self.assertEqual(
                    extract_context_candidates(
                        user_message,
                        "深海魚には多くの種類があります。",
                        llm_json_response=Mock(return_value=candidate_with(evidence)),
                    ),
                    [],
                )

        # 改行や全角半角の違いを跨いでも、本文中の実在する一節なら通過する。
        supported = extract_context_candidates(
            user_message,
            "深海魚には多くの種類があります。",
            llm_json_response=Mock(
                return_value=candidate_with("深海魚って気になるんだけど、 どんな種類がいるの？")
            ),
        )
        self.assertEqual(len(supported), 1)
        # 照合に使った一節は、出典として保存できるようそのまま残る。
        # The span used for the check stays on the candidate so it can be stored as the source.
        self.assertEqual(supported[0]["evidence"], "深海魚って気になるんだけど、 どんな種類がいるの？")

    def test_drops_a_candidate_whose_evidence_contains_a_secret(self):
        # title / content に秘密が無くても、出典として保存される evidence に秘密があれば候補ごと落とす。
        # A candidate is dropped when only its evidence (stored as the source) holds a secret.
        user_message = "I always use Vim. My password is hunter2secret"
        payload = {
            "candidates": [
                {
                    "fact_type": "preference",
                    "title": "Preferred editor",
                    "content": "The user prefers Vim.",
                    "evidence": "I always use Vim. My password is hunter2secret",
                    "importance": 90,
                    "confidence": 0.95,
                },
                {
                    "fact_type": "preference",
                    "title": "Preferred editor",
                    "content": "The user prefers Vim.",
                    "evidence": "I always use Vim",
                    "importance": 90,
                    "confidence": 0.95,
                },
            ]
        }

        accepted = extract_context_candidates(
            user_message, "ok", llm_json_response=Mock(return_value=json.dumps(payload))
        )

        self.assertEqual([candidate["evidence"] for candidate in accepted], ["I always use Vim"])

    def test_bounds_source_text_before_calling_the_extraction_model(self):
        llm = Mock(return_value='{"candidates": []}')

        extract_context_candidates(
            "u" * (MAX_EXTRACTION_USER_MESSAGE_CHARS + 100),
            "a" * (MAX_EXTRACTION_ASSISTANT_RESPONSE_CHARS + 100),
            llm_json_response=llm,
        )

        input_payload = json.loads(llm.call_args.args[0][1]["content"])
        self.assertEqual(len(input_payload["user_message"]), MAX_EXTRACTION_USER_MESSAGE_CHARS)
        self.assertEqual(
            len(input_payload["assistant_response"]),
            MAX_EXTRACTION_ASSISTANT_RESPONSE_CHARS,
        )

    def test_rejects_payloads_that_exceed_bounds_or_include_extra_fields(self):
        invalid_payloads = (
            {
                "candidates": [
                    {
                        "fact_type": "profile",
                        "title": f"Fact {index}",
                        "content": "content",
                        "importance": 50,
                        "confidence": 0.9,
                    }
                    for index in range(4)
                ]
            },
            {
                "candidates": [
                    {
                        "fact_type": "profile",
                        "title": "Profile",
                        "content": "content",
                        "importance": 50,
                        "confidence": 0.9,
                        "unexpected": True,
                    }
                ]
            },
            {
                "candidates": [
                    {
                        "fact_type": "profile",
                        "title": "x" * 101,
                        "content": "content",
                        "importance": 50,
                        "confidence": 0.9,
                    }
                ]
            },
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assertEqual(
                    extract_context_candidates(
                        "user",
                        "assistant",
                        llm_json_response=Mock(return_value=json.dumps(payload)),
                    ),
                    [],
                )

    def test_prompt_lists_the_sensitive_categories_from_the_constant(self):
        prompt = build_extraction_system_prompt("en")

        self.assertGreaterEqual(len(SENSITIVE_CATEGORY_DESCRIPTIONS), 6)
        for name, description in SENSITIVE_CATEGORY_DESCRIPTIONS.items():
            with self.subTest(category=name):
                self.assertIn(f"  - {name}: {description}", prompt)
        self.assertIn("only when user_message itself asks to remember it", prompt)
        self.assertIn("Dietary restrictions are not sensitive", prompt)
        self.assertIn('omit both fields or set them to null, never "none" or another value', prompt)
        self.assertNotIn("{sensitive_categories}", prompt)

    def test_sensitive_section_sits_between_never_extract_and_evidence_requirement(self):
        prompt = build_extraction_system_prompt("en")

        positions = [prompt.index(heading) for heading in ("Never extract:", "Sensitive personal information:", "Evidence requirement:")]
        self.assertEqual(positions, sorted(positions))

    def _sensitive_payload(self, **overrides):
        candidate = {
            "fact_type": "profile",
            "title": "Type 2 diabetes",
            "content": "The user has type 2 diabetes.",
            "evidence": "I have type 2 diabetes",
            "importance": 90,
            "confidence": 0.95,
            "sensitive_category": "health",
            "request_evidence": "Please remember this",
        }
        candidate.update(overrides)
        return json.dumps({"candidates": [candidate]})

    def test_sensitive_candidate_passes_only_with_a_request_span_in_the_user_message(self):
        user_message = "I have type 2 diabetes. Please remember this."

        for category in SENSITIVE_CATEGORY_DESCRIPTIONS:
            with self.subTest(category=category):
                accepted = extract_context_candidates(
                    user_message,
                    "ok",
                    llm_json_response=Mock(return_value=self._sensitive_payload(sensitive_category=category)),
                )
                self.assertEqual([candidate["title"] for candidate in accepted], ["Type 2 diabetes"])

        for label, overrides in (
            ("missing", {"request_evidence": None}),
            ("empty", {"request_evidence": ""}),
            ("whitespace", {"request_evidence": "   "}),
            ("not in the message", {"request_evidence": "Please remember that forever"}),
        ):
            with self.subTest(request=label):
                self.assertEqual(
                    extract_context_candidates(
                        user_message,
                        "ok",
                        llm_json_response=Mock(return_value=self._sensitive_payload(**overrides)),
                    ),
                    [],
                )

    def test_a_request_to_remember_only_in_the_assistant_response_does_not_count(self):
        self.assertEqual(
            extract_context_candidates(
                "I have type 2 diabetes.",
                "Please remember this. I'll keep it in mind.",
                llm_json_response=Mock(return_value=self._sensitive_payload()),
            ),
            [],
        )

    def test_request_span_uses_the_same_normalization_as_evidence(self):
        accepted = extract_context_candidates(
            "I have type 2 diabetes.\nPLEASE  remember this.",
            "ok",
            llm_json_response=Mock(return_value=self._sensitive_payload(request_evidence="ｐｌｅａｓｅ remember this")),
        )

        self.assertEqual(len(accepted), 1)

    def test_an_unlisted_category_makes_only_that_candidate_sensitive(self):
        user_message = "I have type 2 diabetes. Please remember this. I always use Vim"
        vim = {
            "fact_type": "preference",
            "title": "Preferred editor",
            "content": "The user prefers Vim.",
            "evidence": "I always use Vim",
            "importance": 90,
            "confidence": 0.95,
        }
        for category in ("none", "religion", "", "  "):
            with self.subTest(category=category):
                # 依頼の一節が発話に在るなら、その候補だけが通る。
                with_request = json.loads(self._sensitive_payload(sensitive_category=category))
                with_request["candidates"].append(vim)
                accepted = extract_context_candidates(
                    user_message, "ok", llm_json_response=Mock(return_value=json.dumps(with_request))
                )
                self.assertEqual([candidate["title"] for candidate in accepted], ["Type 2 diabetes", "Preferred editor"])
                # 依頼の一節が無ければ、その候補だけが落ち、同じ応答の機微でない候補は残る。
                without_request = json.loads(self._sensitive_payload(sensitive_category=category, request_evidence=None))
                without_request["candidates"].append(vim)
                accepted = extract_context_candidates(
                    user_message, "ok", llm_json_response=Mock(return_value=json.dumps(without_request))
                )
                self.assertEqual([candidate["title"] for candidate in accepted], ["Preferred editor"])

    def test_known_limit_a_sensitive_candidate_without_a_category_is_not_stopped(self):
        # 既知の限界: カテゴリを申告しない候補は機微かどうかをコードでは判定しない（判定は LLM、辞書や正規表現は使わない）。
        # Known limit: a candidate declaring no category is never judged sensitive by the code (the LLM judges, not a dictionary).
        accepted = extract_context_candidates(
            "I have type 2 diabetes.",
            "ok",
            llm_json_response=Mock(return_value=self._sensitive_payload(sensitive_category=None, request_evidence=None)),
        )

        self.assertEqual([candidate["title"] for candidate in accepted], ["Type 2 diabetes"])

    def test_known_limit_the_request_span_is_only_checked_to_be_in_the_user_message(self):
        # 既知の限界: 頼んだ一節は発話に在ることだけを確かめ、依頼かどうかの意味は確かめない。
        # 貼り付けた文書や引用の中の依頼の文、依頼ではない一節、evidence と同じ一節でも通る。
        # Known limit: the span is only checked to be present; whether it is a request is not. A request inside pasted
        # text, a span that is no request, or the same span as evidence all pass.
        user_message = "Here is a forwarded note: 'Please remember this.' I have type 2 diabetes."
        for request_span in ("Please remember this.", "Here is a forwarded note", "I have type 2 diabetes"):
            with self.subTest(request_span=request_span):
                accepted = extract_context_candidates(
                    user_message,
                    "ok",
                    llm_json_response=Mock(return_value=self._sensitive_payload(request_evidence=request_span)),
                )
                self.assertEqual(len(accepted), 1)

    def test_sensitive_fields_are_validated_strictly_and_never_returned(self):
        self.assertEqual(
            extract_context_candidates(
                "I have type 2 diabetes. Please remember this.",
                "ok",
                llm_json_response=Mock(return_value=self._sensitive_payload(sensitive_category=["health"])),
            ),
            [],
        )
        accepted = extract_context_candidates(
            "I have type 2 diabetes. Please remember this.",
            "ok",
            llm_json_response=Mock(return_value=self._sensitive_payload()),
        )
        self.assertEqual(
            accepted,
            [
                {
                    "fact_type": "profile",
                    "title": "Type 2 diabetes",
                    "content": "The user has type 2 diabetes.",
                    "evidence": "I have type 2 diabetes",
                    "importance": 90,
                    "confidence": 0.95,
                }
            ],
        )

    def test_a_sensitive_candidate_still_has_to_pass_the_other_rules(self):
        user_message = "I have type 2 diabetes. Please remember this."
        for overrides in ({"confidence": 0.5}, {"importance": 10}, {"evidence": "I have a cold"}):
            with self.subTest(overrides=overrides):
                self.assertEqual(
                    extract_context_candidates(
                        user_message,
                        "ok",
                        llm_json_response=Mock(return_value=self._sensitive_payload(**overrides)),
                    ),
                    [],
                )

    def test_schedule_submits_work_and_stores_with_chat_source_reference(self):
        submitted = []
        executor = SimpleNamespace(submit=lambda task: submitted.append(task))
        extractor = Mock(
            return_value=[
                {
                    "fact_type": "project",
                    "title": "Project",
                    "content": "Uses FastAPI",
                    "evidence": "We use FastAPI.",
                    "importance": 60,
                    "confidence": 0.95,
                }
            ]
        )
        store = Mock(return_value=1)

        with patch(
            "services.context_vault_extraction.submit_background_task",
            side_effect=executor.submit,
        ):
            schedule_context_extraction(
                42,
                room_id="room-1",
                assistant_message_id=9,
                user_message_id=8,
                user_message="We use FastAPI.",
                assistant_response="Understood.",
                locale="en",
                extractor=extractor,
                store_facts=store,
            )

        self.assertEqual(len(submitted), 1)
        extractor.assert_not_called()
        store.assert_not_called()

        submitted[0]()

        extractor.assert_called_once_with("We use FastAPI.", "Understood.", locale="en")
        store.assert_called_once_with(
            42,
            candidates=extractor.return_value,
            source_ref="chat:room-1:message:9",
            room_id="room-1",
            user_message_id=8,
        )

    def test_background_extraction_errors_are_logged_and_not_raised(self):
        submitted = []
        executor = SimpleNamespace(submit=lambda task: submitted.append(task))
        with (
            patch(
                "services.context_vault_extraction.submit_background_task",
                side_effect=executor.submit,
            ),
            patch("services.context_vault_extraction.logger") as logger,
        ):
            schedule_context_extraction(
                42,
                room_id="room-1",
                assistant_message_id=9,
                user_message="message",
                assistant_response="response",
                extractor=Mock(side_effect=RuntimeError("provider down")),
                store_facts=Mock(),
            )
            submitted[0]()

        logger.warning.assert_called_once()

    def test_executor_submission_errors_are_logged_and_not_raised(self):
        executor = SimpleNamespace(submit=Mock(side_effect=RuntimeError("executor stopped")))
        with (
            patch(
                "services.context_vault_extraction.submit_background_task",
                side_effect=executor.submit,
            ),
            patch("services.context_vault_extraction.logger") as logger,
        ):
            schedule_context_extraction(
                42,
                room_id="room-1",
                assistant_message_id=9,
                user_message="message",
                assistant_response="response",
                extractor=Mock(),
                store_facts=Mock(),
            )

        logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
