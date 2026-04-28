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
        self.assertIn("input → click", messages[0]["content"])
        self.assertIn("select", messages[0]["content"])
        self.assertIn("check", messages[0]["content"])
        self.assertIn("wait", messages[0]["content"])
        self.assertIn("navigate の後に続きの steps", messages[0]["content"])
        self.assertIn("description には変数名", messages[0]["content"])
        self.assertIn("画面上の言葉に言い換える", messages[0]["content"])

    def test_parse_action_response_accepts_typed_app_action_steps(self):
        plan = parse_action_response(
            '{"description":"検索します","steps":[{"action":"app_action","command":"prompt.search",'
            '"args":{"query":"メール返信"},"description":"プロンプトを検索する"}]}'
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"][0]["action"], "app_action")
        self.assertEqual(plan["steps"][0]["command"], "prompt.search")
        self.assertEqual(plan["steps"][0]["args"]["query"], "メール返信")

    def test_parse_action_response_accepts_multi_step_input_then_click(self):
        plan = parse_action_response(
            '{"description":"検索語を入力して検索します","steps":['
            '{"action":"input","selector":"#searchInput","value":"メール返信","description":"検索語を入力する"},'
            '{"action":"click","selector":"#searchButton","description":"検索ボタンを押す"}]}'
        )

        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["steps"]), 2)
        self.assertEqual(plan["steps"][0]["action"], "input")
        self.assertEqual(plan["steps"][0]["value"], "メール返信")
        self.assertEqual(plan["steps"][1]["action"], "click")

    def test_parse_action_response_accepts_navigation_followed_by_action(self):
        plan = parse_action_response(
            '{"description":"プロンプト共有へ移動して検索します","steps":['
            '{"action":"navigate","path":"/prompt_share","description":"プロンプト共有を開く"},'
            '{"action":"input","selector":"#searchInput","value":"メール返信","description":"検索語を入力する"},'
            '{"action":"click","selector":"#searchButton","description":"検索ボタンを押す"}]}'
        )

        self.assertIsNotNone(plan)
        self.assertEqual([step["action"] for step in plan["steps"]], ["navigate", "input", "click"])

    def test_parse_action_response_accepts_select_check_and_wait_steps(self):
        plan = parse_action_response(
            '{"description":"設定を変更します","steps":['
            '{"action":"select","selector":"#theme","value":"dark","description":"テーマを選択する"},'
            '{"action":"check","selector":"#notify","checked":false,"description":"通知をオフにする"},'
            '{"action":"wait","selector":"#save-status","timeout_ms":2400,"description":"保存状態を待つ"}]}'
        )

        self.assertIsNotNone(plan)
        self.assertEqual([step["action"] for step in plan["steps"]], ["select", "check", "wait"])
        self.assertEqual(plan["steps"][0]["value"], "dark")
        self.assertFalse(plan["steps"][1]["checked"])
        self.assertEqual(plan["steps"][2]["timeout_ms"], 2400)

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
