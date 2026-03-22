import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.tasks import prompt_assist
from services.llm import LlmProviderError
from tests.helpers.request_helpers import build_request


def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/prompt-assist",
        json_body=json_body,
        session=session,
    )


class PromptAssistApiTestCase(unittest.TestCase):
    def test_prompt_assist_returns_suggestions(self):
        request = make_request(
            {
                "target": "task_modal",
                "action": "generate_draft",
                "fields": {
                    "title": "メール返信",
                    "prompt_content": "丁寧な返信テンプレートを作りたい",
                },
            }
        )

        with patch(
            "blueprints.chat.tasks.create_prompt_assist_payload",
            return_value={
                "summary": "AIが下書きを作成しました。",
                "warnings": [],
                "suggested_fields": {
                    "title": "丁寧なメール返信テンプレート",
                    "prompt_content": "顧客への丁寧な返信文を作成してください。",
                },
                "model": "openai/gpt-oss-20b",
            },
        ):
            response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["suggested_fields"]["title"], "丁寧なメール返信テンプレート")
        self.assertEqual(payload["model"], "openai/gpt-oss-20b")

    def test_prompt_assist_rejects_improve_without_body(self):
        request = make_request(
            {
                "target": "task_modal",
                "action": "improve",
                "fields": {
                    "title": "メール返信",
                    "prompt_content": "   ",
                },
            }
        )

        response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "本文を入力してからAI補助を実行してください。")

    def test_prompt_assist_returns_retryable_error_on_llm_failure(self):
        request = make_request(
            {
                "target": "shared_prompt_modal",
                "action": "generate_examples",
                "fields": {
                    "title": "学習計画",
                    "content": "学習計画を1週間分作るプロンプト",
                },
            }
        )

        with patch(
            "blueprints.chat.tasks.create_prompt_assist_payload",
            side_effect=LlmProviderError("boom"),
        ):
            response = asyncio.run(prompt_assist(request))

        self.assertEqual(response.status_code, 502)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "AI補助の取得に失敗しました。時間をおいて再試行してください。")


if __name__ == "__main__":
    unittest.main()
