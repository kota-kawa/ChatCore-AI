"""プロンプトアシストのペイロード生成（create_prompt_assist_payload）が LLM の JSON 応答を解析し、
変更のない項目を除き、不正な応答では例外にすることを検証するテスト。

Tests that create_prompt_assist_payload parses the LLM's JSON response, drops unchanged fields,
and raises on an invalid response.
"""

import unittest
from unittest.mock import patch

from services.llm import LlmProviderError
from services.prompt_assist import create_prompt_assist_payload


# 日本語: Prompt Assist Serviceの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Prompt Assist Service.
class PromptAssistServiceTestCase(unittest.TestCase):
    # 日本語: createプロンプトアシストペイロードparsesjsonレスポンスことを検証します。
    # English: Verify that create prompt assist payload parses json response.
    def test_create_prompt_assist_payload_parses_json_response(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "services.prompt_assist.get_llm_response",
            return_value="""```json
{"summary":"本文を整理しました。","warnings":["入力例は仮案です。"],"suggested_fields":{"title":"面接練習プロンプト","prompt_content":"面接官として質問し、最後に改善点を3つ挙げてください。"}}
```""",
        ):
            result = create_prompt_assist_payload(
                "task_modal",
                "generate_draft",
                {
                    "title": "面接",
                    "prompt_content": "面接練習用",
                },
            )

        self.assertEqual(result["summary"], "本文を整理しました。")
        self.assertEqual(result["warnings"], ["入力例は仮案です。"])
        self.assertEqual(result["suggested_fields"]["title"], "面接練習プロンプト")
        self.assertIn("prompt_content", result["suggested_fields"])
        self.assertEqual(result["suggestion_modes"]["title"], "refine")

    # 日本語: createプロンプトアシストペイロードfiltersoutunchangedfieldsことを検証します。
    # English: Verify that create prompt assist payload filters out unchanged fields.
    def test_create_prompt_assist_payload_filters_out_unchanged_fields(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "services.prompt_assist.get_llm_response",
            return_value='{"summary":"タイトルを整えました。","warnings":[],"suggested_fields":{"title":"旅行計画","content":"週末旅行の計画を立ててください。"}}',
        ):
            result = create_prompt_assist_payload(
                "shared_prompt_modal",
                "generate_draft",
                {
                    "title": "旅行計画",
                    "content": "",
                },
            )

        self.assertNotIn("title", result["suggested_fields"])
        self.assertEqual(
            result["suggested_fields"]["content"],
            "週末旅行の計画を立ててください。",
        )
        self.assertEqual(result["suggestion_modes"]["content"], "create")

    # 日本語: 無効なレスポンスに対して、createプロンプトアシストペイロード送出することを検証します。
    # English: Verify that create prompt assist payload raises for invalid response.
    def test_create_prompt_assist_payload_raises_for_invalid_response(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "services.prompt_assist.get_llm_response",
            return_value="not-json",
        ):
            with self.assertRaises(LlmProviderError):
                create_prompt_assist_payload(
                    "shared_prompt_modal",
                    "generate_draft",
                    {
                        "title": "旅行計画",
                        "content": "",
                    },
                )


if __name__ == "__main__":
    unittest.main()
