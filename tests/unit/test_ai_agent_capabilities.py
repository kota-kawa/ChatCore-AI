import unittest
from unittest.mock import patch

from pydantic import ValidationError

from services.agent_capabilities import build_capability_context
from services.intent_classifier import classify_intent
from services.page_actions import build_action_messages, parse_action_response
from services.page_context import get_page_context
from services.request_models import AiAgentRequest


def _validate(model_cls, data):
    validate = getattr(model_cls, "model_validate", None)
    if callable(validate):
        return validate(data)
    return model_cls.parse_obj(data)


class AiAgentCapabilitiesTestCase(unittest.TestCase):
    def test_capability_context_lists_core_features_and_current_actions(self):
        context = build_capability_context("/prompt_share")

        self.assertIn("ChatCore 機能カタログ", context)
        self.assertIn("プロンプト共有", context)
        self.assertIn("#searchInput", context)
        self.assertIn("#heroOpenPostModal", context)
        self.assertIn("command=prompt.search", context)
        self.assertIn("型付きアクションAPI", context)
        self.assertIn("メモ", context)
        self.assertIn("設定", context)

    def test_page_context_includes_capability_catalog_before_source(self):
        context = get_page_context("/settings")

        self.assertIn("ChatCore 機能カタログ", context)
        self.assertIn("現在ページで優先して使える操作: 設定", context)
        self.assertIn("frontend/pages/settings.tsx", context)

    def test_classify_intent_uses_deterministic_action_hints(self):
        with patch("services.intent_classifier.get_llm_response") as mock_llm:
            intent = classify_intent("プロンプト共有ページを開いて", "/")

        self.assertEqual(intent, "action")
        mock_llm.assert_not_called()

    def test_classify_intent_keeps_generation_requests_direct(self):
        with patch("services.intent_classifier.get_llm_response") as mock_llm:
            intent = classify_intent("タイトル案を3つ出して", "/prompt_share")

        self.assertEqual(intent, "direct")
        mock_llm.assert_not_called()

    def test_action_prompt_includes_dom_and_capability_context(self):
        messages = build_action_messages(
            "【現在ブラウザで見えている操作可能要素】\n1. selector=#searchInput; tag=input",
            [{"role": "user", "content": "検索して"}],
        )

        self.assertIn("#searchInput", messages[0]["content"])
        self.assertIn('action": "app_action"', messages[0]["content"])
        self.assertIn("action=\"navigate\"", messages[0]["content"])

    def test_parse_action_response_accepts_typed_app_action_steps(self):
        plan = parse_action_response(
            '{"description":"検索します","steps":[{"action":"app_action","command":"prompt.search",'
            '"args":{"query":"メール返信"},"description":"プロンプトを検索する"}]}'
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"][0]["action"], "app_action")
        self.assertEqual(plan["steps"][0]["command"], "prompt.search")
        self.assertEqual(plan["steps"][0]["args"]["query"], "メール返信")

    def test_parse_action_response_rejects_unknown_app_action_command(self):
        plan = parse_action_response(
            '{"description":"不明な操作","steps":[{"action":"app_action","command":"danger.deleteAll",'
            '"args":{},"description":"危険な操作"}]}'
        )

        self.assertIsNone(plan)

    def test_parse_action_response_accepts_navigation_steps(self):
        plan = parse_action_response(
            '{"description":"設定へ移動します","steps":[{"action":"navigate","path":"/settings","description":"設定を開く"}]}'
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"][0]["action"], "navigate")
        self.assertEqual(plan["steps"][0]["path"], "/settings")

    def test_parse_action_response_rejects_external_navigation(self):
        plan = parse_action_response(
            '{"description":"外部へ移動","steps":[{"action":"navigate","path":"https://example.com","description":"外部"}]}'
        )

        self.assertIsNone(plan)

    def test_ai_agent_request_accepts_dom_context_with_limit(self):
        payload = _validate(
            AiAgentRequest,
            {
                "messages": [{"role": "user", "content": "検索して"}],
                "current_page": "/prompt_share",
                "current_dom": "selector=#searchInput",
            },
        )

        self.assertEqual(payload.current_dom, "selector=#searchInput")

    def test_ai_agent_request_rejects_oversized_dom_context(self):
        with self.assertRaises(ValidationError):
            _validate(
                AiAgentRequest,
                {
                    "messages": [{"role": "user", "content": "検索して"}],
                    "current_dom": "a" * 12001,
                },
            )


if __name__ == "__main__":
    unittest.main()
