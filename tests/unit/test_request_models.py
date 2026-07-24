import unittest

from pydantic import ValidationError

from services.request_models import (
    AddTaskRequest,
    ChatMessageRequest,
    ChatRoomIdsRequest,
    MemoCreateRequest,
    PromptAssistRequest,
    PromptLikeRequest,
    PromptTaskCreateRequest,
    SharedPromptCreateRequest,
    UpdateTasksOrderRequest,
)


# 指定したPydanticモデルクラスを用いて入力データをバリデーションします（v1とv2の互換性を考慮）。
# Validate input data using the specified Pydantic model class (supports v1 and v2 compatibilities).
def _validate(model_cls, data):
    validate = getattr(model_cls, "model_validate", None)
    # model_validate メソッドが存在する場合は呼び出し、存在しない場合は旧 API である parse_obj を使用
    # Call model_validate if it exists, otherwise fall back to parse_obj for backward compatibility
    if callable(validate):
        return validate(data)
    return model_cls.parse_obj(data)


# 各種APIリクエストモデル（Pydantic）のバリデーション仕様を検証するテストクラス。
# Test case class to verify validation behaviors of various API request models (Pydantic).
class RequestModelsTestCase(unittest.TestCase):
    # タスク追加リクエストでタイトルが空文字またはスペースのみの場合、バリデーションエラーになることを検証します。
    # Verify that creating an AddTaskRequest rejects a blank or whitespace-only title.
    def test_add_task_rejects_blank_title(self):
        # タイトルが空欄のときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when the title is empty
        with self.assertRaises(ValidationError):
            _validate(
                AddTaskRequest,
                {"title": "   ", "prompt_content": "prompt"},
            )

    # タスク順序更新リクエストで順序リストが空の場合、バリデーションエラーになることを検証します。
    # Verify that updating tasks order requires a non-empty order list.
    def test_update_tasks_order_requires_non_empty_list(self):
        # 順序リストが空のときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when the order list is empty
        with self.assertRaises(ValidationError):
            _validate(UpdateTasksOrderRequest, {"order": []})

    # メモ作成リクエストでAIの回答内容が空の場合、バリデーションエラーになることを検証します。
    # Verify that memo creation requires a non-empty AI response.
    def test_memo_create_requires_non_empty_ai_response(self):
        # AI回答が空欄のときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when the ai_response is empty
        with self.assertRaises(ValidationError):
            _validate(MemoCreateRequest, {"ai_response": "   "})

    # メモ作成リクエストで有効な背景色コード（HEX形式など）を指定できることを検証します。
    # Verify that memo creation accepts a valid background color hex code.
    def test_memo_create_accepts_background_color(self):
        # 背景色を指定してメモのバリデーションを実行
        # Run memo validation with a background color specified
        payload = _validate(
            MemoCreateRequest,
            {
                "ai_response": "body",
                "title": "メモ",
                "background_color": "#fff8b8",
            },
        )
        self.assertEqual(payload.background_color, "#fff8b8")

    # メモ作成リクエストで不正な形式の背景色（インジェクションの恐れがある値など）が拒否されることを検証します。
    # Verify that memo creation rejects invalid background color format codes.
    def test_memo_create_rejects_invalid_background_color(self):
        # 不正な背景色を指定したときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when background_color is invalid
        with self.assertRaises(ValidationError):
            _validate(
                MemoCreateRequest,
                {
                    "ai_response": "body",
                    "background_color": "url(javascript:alert(1))",
                },
            )

    # 共有プロンプト作成リクエストでタイトルが空文字の場合、バリデーションエラーになることを検証します。
    # Verify that shared prompt creation rejects a blank title.
    def test_prompt_create_rejects_blank_title(self):
        # タイトルが空欄のときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when the title is empty
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

    # 共有プロンプト作成リクエストでカテゴリフィールドが空文字であっても許容されることを検証します。
    # Verify that shared prompt creation accepts a blank category field.
    def test_prompt_create_accepts_blank_category(self):
        # カテゴリを空欄にしてバリデーションを実行
        # Run prompt creation validation with a blank category field
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

    # prompt フォーマットの場合、本文（content）の指定が必須であることを検証します。
    # Verify that prompt creation requires content for the 'prompt' content format.
    def test_prompt_create_requires_content_for_text_type(self):
        # 本文が空欄のときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when content is empty for the prompt format
        with self.assertRaises(ValidationError):
            _validate(
                SharedPromptCreateRequest,
                {
                    "title": "My Prompt",
                    "category": "",
                    "content": "",
                    "author": "author",
                    "content_format": "prompt",
                    "media_type": "text",
                },
            )

    # skill フォーマットの場合、解説用のMarkdown（attributes.skill_markdown）が必須であることを検証します。
    # Verify that the skill format requires attributes.skill_markdown.
    def test_prompt_create_requires_skill_markdown_for_skill_type(self):
        # skill定義Markdownが空欄のときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when skill_markdown is empty for the skill format
        with self.assertRaises(ValidationError):
            _validate(
                SharedPromptCreateRequest,
                {
                    "title": "Skill title",
                    "category": "",
                    "content": "概要",
                    "author": "author",
                    "content_format": "skill",
                    "attributes": {"skill_markdown": "   "},
                },
            )

    # 旧Pythonフィールドを正準リソースへ変換し、新規属性書き込みを停止することを検証します。
    # Verify that the legacy Python field becomes a canonical resource and is not newly persisted as an attribute.
    def test_prompt_create_accepts_skill_payload_with_python_script(self):
        # skill用属性とPythonスクリプトを指定してバリデーションを実行
        # Run validation with skill attributes and a python script
        result = _validate(
            SharedPromptCreateRequest,
            {
                "title": "Skill title",
                "category": "",
                "content": "概要",
                "author": "author",
                "content_format": "skill",
                "attributes": {
                    "skill_markdown": "# Skill",
                    "skill_python_script": "print('hello')",
                },
            },
        )
        self.assertEqual(result.content_format, "skill")
        self.assertEqual(result.attributes["skill_markdown"], "# Skill")
        self.assertNotIn("skill_python_script", result.attributes)
        self.assertEqual(len(result.resources), 1)
        self.assertEqual(result.resources[0].path, "scripts/main.py")
        self.assertEqual(result.resources[0].language, "python")
        self.assertEqual(result.resources[0].content, "print('hello')")

    def test_prompt_create_accepts_multiple_skill_resources(self):
        result = _validate(
            SharedPromptCreateRequest,
            {
                "title": "Skill title",
                "category": "",
                "content_format": "skill",
                "attributes": {"skill_markdown": "# Skill"},
                "resources": [
                    {
                        "path": "scripts/run.ts",
                        "role": "script",
                        "language": "typescript",
                        "content": "export const run = () => true;",
                    },
                    {
                        "path": "references/api.md",
                        "role": "reference",
                        "content": "# API",
                    },
                ],
            },
        )

        self.assertEqual([item.path for item in result.resources], ["scripts/run.ts", "references/api.md"])
        self.assertEqual(result.resources[1].language, "markdown")
        self.assertEqual(result.resources[1].media_type, "text/markdown")

    def test_prompt_create_infers_powershell_resource_language(self):
        result = _validate(
            SharedPromptCreateRequest,
            {
                "title": "PowerShell skill",
                "content_format": "skill",
                "attributes": {"skill_markdown": "# Skill"},
                "resources": [
                    {
                        "path": "scripts/setup.ps1",
                        "role": "script",
                        "content": "Write-Output 'ready'",
                    }
                ],
            },
        )

        self.assertEqual(result.resources[0].language, "powershell")

    def test_prompt_create_rejects_resources_for_non_skill_format(self):
        with self.assertRaises(ValidationError):
            _validate(
                SharedPromptCreateRequest,
                {
                    "title": "Prompt",
                    "content": "body",
                    "resources": [
                        {"path": "scripts/run.py", "role": "script", "content": "print(1)"}
                    ],
                },
            )

    def test_prompt_create_rejects_unsafe_or_secret_resource_paths(self):
        for path in ("../secret.py", "/tmp/run.py", r"scripts\\run.py", ".env", "keys/id_rsa"):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                _validate(
                    SharedPromptCreateRequest,
                    {
                        "title": "Skill",
                        "content_format": "skill",
                        "attributes": {"skill_markdown": "# Skill"},
                        "resources": [{"path": path, "role": "other", "content": "x"}],
                    },
                )

    def test_prompt_create_rejects_case_insensitive_duplicate_resource_paths(self):
        with self.assertRaises(ValidationError):
            _validate(
                SharedPromptCreateRequest,
                {
                    "title": "Skill",
                    "content_format": "skill",
                    "attributes": {"skill_markdown": "# Skill"},
                    "resources": [
                        {"path": "scripts/Run.py", "role": "script", "content": "a"},
                        {"path": "scripts/run.py", "role": "script", "content": "b"},
                    ],
                },
            )

    def test_prompt_create_rejects_reserved_unsupported_and_oversized_resources(self):
        for path, content in (
            ("SKILL.md", "reserved"),
            ("scripts/program.exe", "binary-like"),
            ("scripts/large.py", "x" * (256 * 1024 + 1)),
        ):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                _validate(
                    SharedPromptCreateRequest,
                    {
                        "title": "Skill",
                        "content_format": "skill",
                        "attributes": {"skill_markdown": "# Skill"},
                        "resources": [{"path": path, "role": "other", "content": content}],
                    },
                )

    def test_prompt_create_rejects_oversized_resource_collection(self):
        with self.assertRaises(ValidationError):
            _validate(
                SharedPromptCreateRequest,
                {
                    "title": "Skill",
                    "content_format": "skill",
                    "attributes": {"skill_markdown": "# Skill"},
                    "resources": [
                        {
                            "path": f"references/{index}.txt",
                            "role": "reference",
                            "content": "x" * (220 * 1024),
                        }
                        for index in range(5)
                    ],
                },
            )

    # プロンプトからのタスク作成リクエストで、プロンプトIDをパースして認識できることを検証します。
    # Verify that creating a task from a prompt parses the prompt_id successfully.
    def test_prompt_task_create_uses_prompt_id(self):
        # プロンプトIDを指定してタスク作成用のバリデーションを実行
        # Run validation for prompt task creation with prompt_id
        payload = _validate(
            PromptTaskCreateRequest,
            {"prompt_id": "12"},
        )
        self.assertEqual(payload.prompt_id, 12)

    # いいねリクエストで、プロンプトIDが文字列型であっても自動で整数型へパースされることを検証します。
    # Verify that prompt like request correctly parses string prompt_id to integer type.
    def test_prompt_like_request_parses_prompt_id_type(self):
        # 文字列のIDを渡していいねリクエストのバリデーションを実行
        # Run prompt like request validation with prompt_id as a string value
        payload = _validate(
            PromptLikeRequest,
            {"prompt_id": "24"},
        )
        self.assertEqual(payload.prompt_id, 24)

    # チャットメッセージ送信リクエストで、文字数制限（30,000文字）を超える長い本文が拒否されることを検証します。
    # Verify that chat message rejects an oversized body exceeding character limits.
    def test_chat_message_rejects_oversized_body(self):
        # 30,001文字のメッセージを渡したときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when the message has 30,001 characters
        with self.assertRaises(ValidationError):
            _validate(
                ChatMessageRequest,
                {
                    "message": "a" * 30001,
                    "chat_room_id": "room-1",
                },
            )

    # チャットメッセージ送信リクエストで、Base64形式のバイナリ添付ファイルを受け入れ可能であることを検証します。
    # Verify that chat message accepts binary file attachments encoded in Base64.
    def test_chat_message_accepts_binary_attachment_metadata(self):
        # 添付ファイルメタデータを含めてチャットメッセージのバリデーションを実行
        # Run chat message validation including attached file metadata details
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

    # チャットルームIDリスト送信リクエストで、空のリストが拒否されることを検証します。
    # Verify that chat room IDs request requires a non-empty room list.
    def test_chat_room_ids_requires_non_empty_list(self):
        # ルームIDリストが空のときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when the room IDs list is empty
        with self.assertRaises(ValidationError):
            _validate(ChatRoomIdsRequest, {"room_ids": []})

    # チャットルームIDリスト送信リクエストで、上限（100件）を超える件数が指定された場合に拒否されることを検証します。
    # Verify that chat room IDs request rejects a list with more than 100 rooms.
    def test_chat_room_ids_rejects_more_than_100_rooms(self):
        # 101件のルームIDリストを渡したときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when there are 101 room IDs in the list
        with self.assertRaises(ValidationError):
            _validate(ChatRoomIdsRequest, {"room_ids": [str(index) for index in range(101)]})

    # チャットルームIDリスト送信リクエストで、リスト内に空欄やスペースのみのルームIDが含まれる場合に拒否されることを検証します。
    # Verify that chat room IDs request rejects any blank or whitespace-only room ID in the list.
    def test_chat_room_ids_rejects_blank_room_id(self):
        # 空白のIDを含むリストを渡したときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when there is an empty ID string in the list
        with self.assertRaises(ValidationError):
            _validate(ChatRoomIdsRequest, {"room_ids": ["room-1", "   "]})

    # アシスト機能（プロンプト生成・ドラフト作成など）のリクエストで、規定サイズを超える長いフィールド入力値が拒否されることを検証します。
    # Verify that prompt assist request rejects oversized input fields.
    def test_prompt_assist_rejects_oversized_fields(self):
        # 規定文字数を超えるタスク内容を指定したときに ValidationError が発生することを確認
        # Check that a ValidationError is raised when prompt_content exceeds allowed limits
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
