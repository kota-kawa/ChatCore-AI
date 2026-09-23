import asyncio
import unittest
from unittest.mock import patch

from blueprints.prompt_share import manage_prompts
from tests.helpers.request_helpers import build_request


# 日本語: プロンプト共有のページ用ルート（Next.js への転送）の挙動を検証するクラス。
# English: Test class for the prompt share page routes that forward to the Next.js frontend.
class PromptSharePageRoutesTestCase(unittest.TestCase):
    # 日本語: 旧「投稿したプロンプト」画面の URL が、設定画面の該当セクションへ恒久転送されることを検証します。
    # English: Verify that the legacy posted-prompts URL permanently redirects to the settings section.
    def test_manage_prompts_redirects_to_settings_prompts_section(self):
        request = build_request(path="/prompt_share/manage_prompts")
        with patch("services.web_constants.FRONTEND_URL", "https://chatcore-ai.com"):
            response = asyncio.run(manage_prompts(request))

        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.headers["location"], "https://chatcore-ai.com/settings?section=prompts")


if __name__ == "__main__":
    unittest.main()
