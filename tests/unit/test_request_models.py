import unittest

from pydantic import ValidationError

from services.request_models import (
    AddTaskRequest,
    BookmarkCreateRequest,
    ChatMessageRequest,
    ChatRoomIdsRequest,
    MemoCreateRequest,
    PromptAssistRequest,
    PromptLikeRequest,
    PromptListEntryCreateRequest,
    PromptTaskCreateRequest,
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
            _validate(MemoCreateRequest, {"ai_response": "   "})

    def test_memo_create_accepts_background_color(self):
        payload = _validate(
            MemoCreateRequest,
            {
                "ai_response": "body",
                "title": "メモ",
                "background_color": "#fff8b8",
            },
        )
        self.assertEqual(payload.background_color, "#fff8b8")

    def test_memo_create_rejects_invalid_background_color(self):
        with self.assertRaises(ValidationError):
            _validate(
                MemoCreateRequest,
                {
                    "ai_response": "body",
                    "background_color": "url(javascript:alert(1))",
                },
            )

    def test_prompt_create_rejects_blank_title(self):
        with self.assertRaises(ValidationError):
            _validate(
                SharedPromptCreateRequest,
                {
                    "title": "   ",
                    "category": "",
                    "content": "content",
                    "author": "author",
                },
            )

    def test_prompt_create_accepts_blank_category(self):
        result = _validate(
            SharedPromptCreateRequest,
            {
                "title": "title",
                "category": "",
                "content": "content",
                "author": "author",
            },
        )
        self.assertEqual(result.category, "")

    def test_prompt_create_requires_content_for_text_type(self):
        with self.assertRaises(ValidationError):
            _validate(
                SharedPromptCreateRequest,
                {
                    "title": "My Prompt",
                    "category": "",
                    "content": "",
                    "author": "author",
                    "prompt_type": "text",
                },
            )

    def test_prompt_create_requires_skill_markdown_for_skill_type(self):
        with self.assertRaises(ValidationError):
            _validate(
                SharedPromptCreateRequest,
                {
                    "title": "Skill title",
                    "category": "",
                    "content": "概要",
                    "author": "author",
                    "prompt_type": "skill",
                    "skill_markdown": "   ",
                },
            )

    def test_prompt_create_accepts_skill_payload_with_python_script(self):
        result = _validate(
            SharedPromptCreateRequest,
            {
                "title": "Skill title",
                "category": "",
                "content": "概要",
                "author": "author",
                "prompt_type": "skill",
                "skill_markdown": "# Skill",
                "skill_python_script": "print('hello')",
            },
        )
        self.assertEqual(result.prompt_type, "skill")
        self.assertEqual(result.skill_markdown, "# Skill")

    def test_prompt_list_entry_parses_prompt_id_type(self):
        payload = _validate(
            PromptListEntryCreateRequest,
            {"prompt_id": "12"},
        )
        self.assertEqual(payload.prompt_id, 12)

    def test_prompt_list_entry_requires_prompt_id(self):
        with self.assertRaises(ValidationError):
            _validate(PromptListEntryCreateRequest, {})

    def test_bookmark_create_uses_prompt_id(self):
        payload = _validate(
            BookmarkCreateRequest,
            {"prompt_id": "12"},
        )
        self.assertEqual(payload.prompt_id, 12)

    def test_prompt_task_create_uses_prompt_id(self):
        payload = _validate(
            PromptTaskCreateRequest,
            {"prompt_id": "12"},
        )
        self.assertEqual(payload.prompt_id, 12)

    def test_prompt_like_request_parses_prompt_id_type(self):
        payload = _validate(
            PromptLikeRequest,
            {"prompt_id": "24"},
        )
        self.assertEqual(payload.prompt_id, 24)

    def test_chat_message_rejects_oversized_body(self):
        with self.assertRaises(ValidationError):
            _validate(
                ChatMessageRequest,
                {
                    "message": "a" * 30001,
                    "chat_room_id": "room-1",
                },
            )

    def test_chat_message_accepts_binary_attachment_metadata(self):
        payload = _validate(
            ChatMessageRequest,
            {
                "message": "この資料を要約して",
                "chat_room_id": "room-1",
                "attached_files": [
                    {
                        "name": "document.pdf",
                        "media_type": "application/pdf",
                        "data_base64": "QUJD",
                    }
                ],
            },
        )

        self.assertEqual(payload.attached_files[0].name, "document.pdf")
        self.assertEqual(payload.attached_files[0].data_base64, "QUJD")

    def test_chat_room_ids_requires_non_empty_list(self):
        with self.assertRaises(ValidationError):
            _validate(ChatRoomIdsRequest, {"room_ids": []})

    def test_chat_room_ids_rejects_more_than_100_rooms(self):
        with self.assertRaises(ValidationError):
            _validate(ChatRoomIdsRequest, {"room_ids": [str(index) for index in range(101)]})

    def test_chat_room_ids_rejects_blank_room_id(self):
        with self.assertRaises(ValidationError):
            _validate(ChatRoomIdsRequest, {"room_ids": ["room-1", "   "]})

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
