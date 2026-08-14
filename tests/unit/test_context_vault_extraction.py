import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.context_vault_extraction import (
    MAX_EXTRACTION_ASSISTANT_RESPONSE_CHARS,
    MAX_EXTRACTION_USER_MESSAGE_CHARS,
    build_extraction_system_prompt,
    extract_context_candidates,
    schedule_context_extraction,
)


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
                    "importance": 80,
                    "confidence": 0.95,
                }
            ],
        )
        messages, model = llm.call_args.args
        self.assertEqual(model, "openai/gpt-oss-120b")
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

    def test_prompt_requires_conversation_language_and_rejects_momentary_curiosity(self):
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
        self.assertNotIn("evidence", supported[0])

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

    def test_schedule_submits_work_and_stores_with_chat_source_reference(self):
        submitted = []
        executor = SimpleNamespace(submit=lambda task: submitted.append(task))
        extractor = Mock(
            return_value=[
                {
                    "fact_type": "project",
                    "title": "Project",
                    "content": "Uses FastAPI",
                    "importance": 60,
                    "confidence": 0.95,
                }
            ]
        )
        store = Mock(return_value=1)

        with patch(
            "services.context_vault_extraction.get_background_executor",
            return_value=executor,
        ):
            schedule_context_extraction(
                42,
                room_id="room-1",
                assistant_message_id=9,
                user_message="We use FastAPI.",
                assistant_response="Understood.",
                locale="en",
                extractor=extractor,
                store_candidates=store,
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
        )

    def test_background_extraction_errors_are_logged_and_not_raised(self):
        submitted = []
        executor = SimpleNamespace(submit=lambda task: submitted.append(task))
        with (
            patch(
                "services.context_vault_extraction.get_background_executor",
                return_value=executor,
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
                store_candidates=Mock(),
            )
            submitted[0]()

        logger.warning.assert_called_once()

    def test_executor_submission_errors_are_logged_and_not_raised(self):
        executor = SimpleNamespace(submit=Mock(side_effect=RuntimeError("executor stopped")))
        with (
            patch(
                "services.context_vault_extraction.get_background_executor",
                return_value=executor,
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
                store_candidates=Mock(),
            )

        logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
