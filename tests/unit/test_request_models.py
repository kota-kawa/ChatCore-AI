import unittest

from pydantic import ValidationError

from services.request_models import (
    AddTaskRequest,
    ChatMessageRequest,
    MemoCreateRequest,
    PromptAssistRequest,
    PromptListEntryCreateRequest,
    SharedPromptCreateRequest,
    UpdateTasksOrderRequest,
)


def _validate(model_cls, data):
    validate = getattr(model_cls, "model_validate", None)
    if callable(validate):
        return validate(data)
    return model_cls.parse_obj(data)


class RequestModelsTestCase(unittest.TestCase):
    def test_add_task_rejects_blank_title(self):
        with self.assertRaises(ValidationError):
            _validate(
                AddTaskRequest,
                {"title": "   ", "prompt_content": "prompt"},
            )

    def test_update_tasks_order_requires_non_empty_list(self):
        with self.assertRaises(ValidationError):
            _validate(UpdateTasksOrderRequest, {"order": []})

    def test_memo_create_requires_non_empty_ai_response(self):
        with self.assertRaises(ValidationError):
            _validate(MemoCreateRequest, {"input_content": "foo", "ai_response": "   "})

    def test_prompt_create_rejects_blank_required_field(self):
        with self.assertRaises(ValidationError):
            _validate(
                SharedPromptCreateRequest,
                {
                    "title": "title",
                    "category": "   ",
                    "content": "content",
                    "author": "author",
                },
            )

    def test_prompt_list_entry_parses_prompt_id_type(self):
        payload = _validate(
            PromptListEntryCreateRequest,
            {"prompt_id": "12"},
        )
        self.assertEqual(payload.prompt_id, 12)

    def test_prompt_list_entry_requires_prompt_id(self):
        with self.assertRaises(ValidationError):
            _validate(PromptListEntryCreateRequest, {})

    def test_chat_message_rejects_oversized_body(self):
        with self.assertRaises(ValidationError):
            _validate(
                ChatMessageRequest,
                {
                    "message": "a" * 30001,
                    "chat_room_id": "room-1",
                },
            )

    def test_prompt_assist_rejects_oversized_fields(self):
        with self.assertRaises(ValidationError):
            _validate(
                PromptAssistRequest,
                {
                    "target": "task_modal",
                    "action": "generate_draft",
                    "fields": {
                        "prompt_content": "a" * 4001,
                    },
                },
            )


if __name__ == "__main__":
    unittest.main()
