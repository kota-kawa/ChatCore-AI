import unittest

from services.chat_context import GENERATIVE_UI_EXECUTION_CONTRACT
from services.generative_ui import (
    MAX_ARTIFACT_CSS_CHARS,
    MAX_ARTIFACT_HEIGHT,
    MAX_ARTIFACT_HTML_CHARS,
    MAX_ARTIFACT_JS_CHARS,
    MAX_ARTIFACT_TOTAL_CHARS,
    MIN_ARTIFACT_HEIGHT,
    normalize_response_with_artifacts,
)


def _non_text_parts(parts) -> list:
    return [part for part in (parts or []) if part.get("type") != "text"]


def _artifact_message(js: str) -> str:
    return (
        "生成しました。\n\n"
        "```chatcore-artifact\n"
        '{"version":1,"title":"t","height":300,'
        '"html":"<div id=\'app\'></div>","css":"","js":"' + js + '"}\n'
        "```"
    )


# 日本語: サンドボックスの禁止事項がプロンプトに明記され、バリデータと一致していることを検証するクラス。
# English: Test class asserting the sandbox limits are stated in the prompt and
# stay consistent with what the validator actually enforces.
class GenerativeUiContractTestCase(unittest.TestCase):
    # 日本語: バリデータが拒否する主要APIが、すべてプロンプトで禁止として示されていることを検証します。
    # English: Verify every major API the validator rejects is named in the prompt.
    def test_contract_names_the_banned_capabilities(self):
        for banned in (
            "fetch",
            "XMLHttpRequest",
            "WebSocket",
            "EventSource",
            "sendBeacon",
            "importScripts",
            "localStorage",
            "sessionStorage",
            "indexedDB",
            "document.cookie",
            "eval",
            "postMessage",
            "location",
        ):
            with self.subTest(banned=banned):
                self.assertIn(banned, GENERATIVE_UI_EXECUTION_CONTRACT)

    # 日本語: プロンプトに書かれたサイズ上限が、実際の検証値と一致することを検証します。
    # English: Verify the limits quoted in the prompt match the enforced values.
    def test_contract_quotes_the_enforced_limits(self):
        for limit in (
            MAX_ARTIFACT_HTML_CHARS,
            MAX_ARTIFACT_CSS_CHARS,
            MAX_ARTIFACT_JS_CHARS,
            MAX_ARTIFACT_TOTAL_CHARS,
            MIN_ARTIFACT_HEIGHT,
            MAX_ARTIFACT_HEIGHT,
        ):
            with self.subTest(limit=limit):
                self.assertIn(str(limit), GENERATIVE_UI_EXECUTION_CONTRACT)

    # 日本語: 禁止APIを使うと Artifact が丸ごと失われることを検証します（プロンプトで警告する理由）。
    # English: Verify a banned API costs the user the whole Artifact, which is why
    # the prompt must warn about it.
    def test_banned_api_drops_the_whole_artifact(self):
        normalized = normalize_response_with_artifacts(
            _artifact_message("fetch('/api/data');"),
            recover_truncated=True,
            artifact_intent_text="グラフを作って",
        )

        self.assertTrue(normalized.validation_errors)
        self.assertFalse(
            _non_text_parts(normalized.parts),
            "an artifact using a banned API must not reach the user",
        )

    # 日本語: 制約を守った Artifact は通常どおり生成されることを検証します。
    # English: Verify a compliant Artifact still passes through.
    def test_compliant_artifact_is_kept(self):
        normalized = normalize_response_with_artifacts(
            _artifact_message(
                "document.getElementById('app').textContent = 'ok';"
            ),
            recover_truncated=True,
            artifact_intent_text="グラフを作って",
        )

        self.assertEqual(normalized.validation_errors, [])
        self.assertTrue(_non_text_parts(normalized.parts))


if __name__ == "__main__":
    unittest.main()
