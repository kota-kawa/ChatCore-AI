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


# 日本語: validate の検証処理を担当します。
# English: Handle validating for validate.
def _validate(model_cls, data):
    validate = getattr(model_cls, "model_validate", None)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if callable(validate):
        return validate(data)
    return model_cls.parse_obj(data)


# 日本語: RequestModelsTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to RequestModelsTestCase.
class RequestModelsTestCase(unittest.TestCase):
    # 日本語: test add task rejects blank title のテスト検証を担当します。
    # English: Handle verifying test behavior for test add task rejects blank title.
    def test_add_task_rejects_blank_title(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaises(ValidationError):
            _validate(
                AddTaskRequest,
                {"title": "   ", "prompt_content": "prompt"},
            )

    # 日本語: test update tasks order requires non empty list のテスト検証を担当します。
    # English: Handle verifying test behavior for test update tasks order requires non empty list.
    def test_update_tasks_order_requires_non_empty_list(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaises(ValidationError):
            _validate(UpdateTasksOrderRequest, {"order": []})

    # 日本語: test memo create requires non empty ai response のテスト検証を担当します。
    # English: Handle verifying test behavior for test memo create requires non empty ai response.
    def test_memo_create_requires_non_empty_ai_response(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaises(ValidationError):
            _validate(MemoCreateRequest, {"ai_response": "   "})

    # 日本語: test memo create accepts background color のテスト検証を担当します。
    # English: Handle verifying test behavior for test memo create accepts background color.
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

    # 日本語: test memo create rejects invalid background color のテスト検証を担当します。
    # English: Handle verifying test behavior for test memo create rejects invalid background color.
    def test_memo_create_rejects_invalid_background_color(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaises(ValidationError):
            _validate(
                MemoCreateRequest,
                {
                    "ai_response": "body",
                    "background_color": "url(javascript:alert(1))",
                },
            )

    # 日本語: test prompt create rejects blank title のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt create rejects blank title.
    def test_prompt_create_rejects_blank_title(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test prompt create accepts blank category のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt create accepts blank category.
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

    # 日本語: test prompt create requires content for text type のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt create requires content for text type.
    def test_prompt_create_requires_content_for_text_type(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test prompt create requires skill markdown for skill type のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt create requires skill markdown for skill type.
    def test_prompt_create_requires_skill_markdown_for_skill_type(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test prompt create accepts skill payload with python script のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt create accepts skill payload with python script.
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

    # 日本語: test prompt list entry parses prompt id type のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt list entry parses prompt id type.
    def test_prompt_list_entry_parses_prompt_id_type(self):
        payload = _validate(
            PromptListEntryCreateRequest,
            {"prompt_id": "12"},
        )
        self.assertEqual(payload.prompt_id, 12)

    # 日本語: test prompt list entry requires prompt id のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt list entry requires prompt id.
    def test_prompt_list_entry_requires_prompt_id(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaises(ValidationError):
            _validate(PromptListEntryCreateRequest, {})

    # 日本語: test bookmark create uses prompt id のテスト検証を担当します。
    # English: Handle verifying test behavior for test bookmark create uses prompt id.
    def test_bookmark_create_uses_prompt_id(self):
        payload = _validate(
            BookmarkCreateRequest,
            {"prompt_id": "12"},
        )
        self.assertEqual(payload.prompt_id, 12)

    # 日本語: test prompt task create uses prompt id のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt task create uses prompt id.
    def test_prompt_task_create_uses_prompt_id(self):
        payload = _validate(
            PromptTaskCreateRequest,
            {"prompt_id": "12"},
        )
        self.assertEqual(payload.prompt_id, 12)

    # 日本語: test prompt like request parses prompt id type のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt like request parses prompt id type.
    def test_prompt_like_request_parses_prompt_id_type(self):
        payload = _validate(
            PromptLikeRequest,
            {"prompt_id": "24"},
        )
        self.assertEqual(payload.prompt_id, 24)

    # 日本語: test chat message rejects oversized body のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat message rejects oversized body.
    def test_chat_message_rejects_oversized_body(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaises(ValidationError):
            _validate(
                ChatMessageRequest,
                {
                    "message": "a" * 30001,
                    "chat_room_id": "room-1",
                },
            )

    # 日本語: test chat message accepts binary attachment metadata のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat message accepts binary attachment metadata.
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

    # 日本語: test chat room ids requires non empty list のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat room ids requires non empty list.
    def test_chat_room_ids_requires_non_empty_list(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaises(ValidationError):
            _validate(ChatRoomIdsRequest, {"room_ids": []})

    # 日本語: test chat room ids rejects more than 100 rooms のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat room ids rejects more than 100 rooms.
    def test_chat_room_ids_rejects_more_than_100_rooms(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaises(ValidationError):
            _validate(ChatRoomIdsRequest, {"room_ids": [str(index) for index in range(101)]})

    # 日本語: test chat room ids rejects blank room id のテスト検証を担当します。
    # English: Handle verifying test behavior for test chat room ids rejects blank room id.
    def test_chat_room_ids_rejects_blank_room_id(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self.assertRaises(ValidationError):
            _validate(ChatRoomIdsRequest, {"room_ids": ["room-1", "   "]})

    # 日本語: test prompt assist rejects oversized fields のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt assist rejects oversized fields.
    def test_prompt_assist_rejects_oversized_fields(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
