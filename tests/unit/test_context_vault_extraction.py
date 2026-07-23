import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.context_vault_extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    MAX_EXTRACTION_ASSISTANT_RESPONSE_CHARS,
    MAX_EXTRACTION_USER_MESSAGE_CHARS,
    extract_context_candidates,
    schedule_context_extraction,
)


class ContextVaultExtractionTestCase(unittest.TestCase):
    def test_extracts_only_high_confidence_non_secret_candidates_with_selected_model(self):
        llm = Mock(
            return_value=json.dumps(
                {
                    "candidates": [
                        {
                            "fact_type": "preference",
                            "title": "Preferred editor",
                            "content": "The user prefers Vim.",
                            "importance": 70,
                            "confidence": 0.95,
                        },
                        {
                            "fact_type": "profile",
                            "title": "Possible location",
                            "content": "The user may live in Tokyo.",
                            "importance": 40,
                            "confidence": 0.4,
                        },
                        {
                            "fact_type": "reference",
                            "title": "API credential",
                            "content": "API key: sk-1234567890abcdefghijklmnop",
                            "importance": 100,
                            "confidence": 0.99,
                        },
                    ]
                }
            )
        )

        candidates = extract_context_candidates(
            "I prefer Vim. My API key is secret.",
            "I will remember that you like Vim.",
            "selected-model",
            llm_json_response=llm,
        )

        self.assertEqual(
            candidates,
            [
                {
                    "fact_type": "preference",
                    "title": "Preferred editor",
                    "content": "The user prefers Vim.",
                    "importance": 70,
                    "confidence": 0.95,
                }
            ],
        )
        messages, model = llm.call_args.args
        self.assertEqual(model, "selected-model")
        self.assertEqual(len(messages), 2)
        self.assertEqual(
            json.loads(messages[1]["content"])["user_message"],
            "I prefer Vim. My API key is secret.",
        )
        self.assertEqual(
            json.loads(messages[1]["content"])["assistant_response"],
            "I will remember that you like Vim.",
        )
        self.assertIn("ユーザー本人が明言", EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("AIが新しく提示・推測・推薦した情報は抽出しません", EXTRACTION_SYSTEM_PROMPT)

    def test_bounds_source_text_before_calling_the_extraction_model(self):
        llm = Mock(return_value='{"candidates": []}')

        extract_context_candidates(
            "u" * (MAX_EXTRACTION_USER_MESSAGE_CHARS + 100),
            "a" * (MAX_EXTRACTION_ASSISTANT_RESPONSE_CHARS + 100),
            "selected-model",
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
                        "model",
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
                model="same-model",
                extractor=extractor,
                store_candidates=store,
            )

        self.assertEqual(len(submitted), 1)
        extractor.assert_not_called()
        store.assert_not_called()

        submitted[0]()

        extractor.assert_called_once_with("We use FastAPI.", "Understood.", "same-model")
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
                model="model",
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
                model="model",
                extractor=Mock(),
                store_candidates=Mock(),
            )

        logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
