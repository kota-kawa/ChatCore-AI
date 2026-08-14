import unittest

from blueprints.chat import messages as chat_messages
from services import chat_context
from services.chat_prompt import (
    BASE_SYSTEM_PROMPT,
    GENERATIVE_UI_EXECUTION_CONTRACT,
    build_base_system_prompt,
    build_task_prompt,
    build_user_profile_prompt,
    insert_after_leading_system_messages,
)


class ChatPromptManagementTestCase(unittest.TestCase):
    # 日本語: Blueprintと文脈モジュールの互換名が、中央管理された定義そのものを再公開することを検証します。
    # English: Verify compatibility names re-export the centrally managed definitions themselves.
    def test_legacy_import_paths_reexport_canonical_prompt_definitions(self):
        self.assertIs(chat_messages.BASE_SYSTEM_PROMPT, BASE_SYSTEM_PROMPT)
        self.assertIs(chat_messages._build_base_system_prompt, build_base_system_prompt)
        self.assertIs(chat_messages._build_user_profile_prompt, build_user_profile_prompt)
        self.assertIs(chat_messages._build_task_prompt, build_task_prompt)
        self.assertIs(
            chat_context.GENERATIVE_UI_EXECUTION_CONTRACT,
            GENERATIVE_UI_EXECUTION_CONTRACT,
        )

    # 日本語: 動的な参照文脈が、先頭のsystem群の直後かつ会話履歴の前へ挿入されることを検証します。
    # English: Verify dynamic reference context is inserted after leading system messages and before history.
    def test_insert_after_leading_system_messages_preserves_order(self):
        messages = [
            {"role": "system", "content": "base"},
            {"role": "system", "content": "contract"},
            {"role": "user", "content": "question"},
        ]
        context = {"role": "system", "content": "evidence"}

        result = insert_after_leading_system_messages(messages, context)

        self.assertEqual(
            [message["content"] for message in result],
            ["base", "contract", "evidence", "question"],
        )
        self.assertEqual(
            [message["content"] for message in messages],
            ["base", "contract", "question"],
        )


if __name__ == "__main__":
    unittest.main()
