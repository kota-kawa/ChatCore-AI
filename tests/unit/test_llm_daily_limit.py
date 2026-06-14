import os
import unittest
from unittest.mock import patch

from services import llm_daily_limit


# 日本語: Llm Daily Limitの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Llm Daily Limit.
class LlmDailyLimitTestCase(unittest.TestCase):
    # 日本語: テスト用の処理の入口関数setUpです。
# English: Entry point helper function setUp for testing.
    def setUp(self):
        self.original_limit = os.environ.get("LLM_DAILY_API_LIMIT")
        self.original_auth_email_limit = os.environ.get("AUTH_EMAIL_DAILY_SEND_LIMIT")
        self.original_ai_agent_limit = os.environ.get("AI_AGENT_MONTHLY_API_LIMIT")
        self.original_brave_search_limit = os.environ.get("BRAVE_WEB_SEARCH_MONTHLY_LIMIT")
        llm_daily_limit.clear_in_memory_daily_limit_state()

    # 日本語: テスト用の処理の入口関数tearDownです。
# English: Entry point helper function tearDown for testing.
    def tearDown(self):
        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if self.original_limit is None:
            os.environ.pop("LLM_DAILY_API_LIMIT", None)
        else:
            os.environ["LLM_DAILY_API_LIMIT"] = self.original_limit

        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if self.original_auth_email_limit is None:
            os.environ.pop("AUTH_EMAIL_DAILY_SEND_LIMIT", None)
        else:
            os.environ["AUTH_EMAIL_DAILY_SEND_LIMIT"] = self.original_auth_email_limit

        if self.original_ai_agent_limit is None:
            os.environ.pop("AI_AGENT_MONTHLY_API_LIMIT", None)
        else:
            os.environ["AI_AGENT_MONTHLY_API_LIMIT"] = self.original_ai_agent_limit

        if self.original_brave_search_limit is None:
            os.environ.pop("BRAVE_WEB_SEARCH_MONTHLY_LIMIT", None)
        else:
            os.environ["BRAVE_WEB_SEARCH_MONTHLY_LIMIT"] = self.original_brave_search_limit

        llm_daily_limit.clear_in_memory_daily_limit_state()

    # 日本語: reachingcapの後、カスタム制限ブロックすることを検証します。
    # English: Verify that custom limit blocks after reaching cap.
    def test_custom_limit_blocks_after_reaching_cap(self):
        os.environ["LLM_DAILY_API_LIMIT"] = "2"

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            first = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")
            second = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")
            third = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")

        self.assertEqual(first, (True, 1, 2))
        self.assertEqual(second, (True, 0, 2))
        self.assertEqual(third, (False, 0, 2))

    # 日本語: 次のdayにおける、counterresetsことを検証します。
    # English: Verify that counter resets on next day.
    def test_counter_resets_on_next_day(self):
        os.environ["LLM_DAILY_API_LIMIT"] = "1"

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            day1 = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")
            day1_exceeded = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")
            day2 = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-27")

        self.assertEqual(day1, (True, 0, 1))
        self.assertEqual(day1_exceeded, (False, 0, 1))
        self.assertEqual(day2, (True, 0, 1))

    # 日本語: デフォルトへ、無効なenvvaluefallsことを検証します。
    # English: Verify that invalid env value falls back to default.
    def test_invalid_env_value_falls_back_to_default(self):
        os.environ["LLM_DAILY_API_LIMIT"] = "not-a-number"

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            allowed, remaining, limit = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")

        self.assertTrue(allowed)
        self.assertEqual(limit, llm_daily_limit.DEFAULT_LLM_DAILY_API_LIMIT)
        self.assertEqual(remaining, llm_daily_limit.DEFAULT_LLM_DAILY_API_LIMIT - 1)

    # 日本語: reachingcapの後、認証メール制限ブロックすることを検証します。
    # English: Verify that auth email limit blocks after reaching cap.
    def test_auth_email_limit_blocks_after_reaching_cap(self):
        os.environ["AUTH_EMAIL_DAILY_SEND_LIMIT"] = "2"

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            first = llm_daily_limit.consume_auth_email_daily_quota(current_date="2026-02-26")
            second = llm_daily_limit.consume_auth_email_daily_quota(current_date="2026-02-26")
            third = llm_daily_limit.consume_auth_email_daily_quota(current_date="2026-02-26")

        self.assertEqual(first, (True, 1, 2))
        self.assertEqual(second, (True, 0, 2))
        self.assertEqual(third, (False, 0, 2))

    # 日本語: reachingcapの後、aiagentmonthly制限ブロックすることを検証します。
    # English: Verify that ai agent monthly limit blocks after reaching cap.
    def test_ai_agent_monthly_limit_blocks_after_reaching_cap(self):
        os.environ["AI_AGENT_MONTHLY_API_LIMIT"] = "2"

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            first = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-02")
            second = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-02")
            third = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-02")

        self.assertEqual(first, (True, 1, 2))
        self.assertEqual(second, (True, 0, 2))
        self.assertEqual(third, (False, 0, 2))

    # 日本語: 次のmonthにおける、aiagentmonthlycounterresetsことを検証します。
    # English: Verify that ai agent monthly counter resets on next month.
    def test_ai_agent_monthly_counter_resets_on_next_month(self):
        os.environ["AI_AGENT_MONTHLY_API_LIMIT"] = "1"

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            month1 = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-02")
            month1_exceeded = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-02")
            month2 = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-03")

        self.assertEqual(month1, (True, 0, 1))
        self.assertEqual(month1_exceeded, (False, 0, 1))
        self.assertEqual(month2, (True, 0, 1))

    # 日本語: reachingcapの後、braveWeb検索monthly制限ブロックすることを検証します。
    # English: Verify that brave web search monthly limit blocks after reaching cap.
    def test_brave_web_search_monthly_limit_blocks_after_reaching_cap(self):
        os.environ["BRAVE_WEB_SEARCH_MONTHLY_LIMIT"] = "2"

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            first = llm_daily_limit.consume_brave_web_search_monthly_quota(current_month="2026-02")
            second = llm_daily_limit.consume_brave_web_search_monthly_quota(current_month="2026-02")
            third = llm_daily_limit.consume_brave_web_search_monthly_quota(current_month="2026-02")

        self.assertEqual(first, (True, 1, 2))
        self.assertEqual(second, (True, 0, 2))
        self.assertEqual(third, (False, 0, 2))

    # 日本語: perユーザークォータdoes〜しないdrainotherusersことを検証します。
    # English: Verify that per user quota does not drain other users.
    def test_per_user_quota_does_not_drain_other_users(self):
        # Regression guard: a single user must not be able to deny service to
        # everyone else by burning the global daily budget.
        os.environ["LLM_DAILY_API_LIMIT"] = "2"

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            a1 = llm_daily_limit.consume_llm_daily_quota(
                current_date="2026-02-26", user_key="user:1"
            )
            a2 = llm_daily_limit.consume_llm_daily_quota(
                current_date="2026-02-26", user_key="user:1"
            )
            a3 = llm_daily_limit.consume_llm_daily_quota(
                current_date="2026-02-26", user_key="user:1"
            )
            # user 2 must still have a fresh budget despite user 1 being capped
            b1 = llm_daily_limit.consume_llm_daily_quota(
                current_date="2026-02-26", user_key="user:2"
            )
            b2 = llm_daily_limit.consume_llm_daily_quota(
                current_date="2026-02-26", user_key="user:2"
            )

        self.assertEqual(a1, (True, 1, 2))
        self.assertEqual(a2, (True, 0, 2))
        self.assertEqual(a3, (False, 0, 2))
        self.assertEqual(b1, (True, 1, 2))
        self.assertEqual(b2, (True, 0, 2))

    # 日本語: 500へ、braveWeb検索monthly制限defaultsことを検証します。
    # English: Verify that brave web search monthly limit defaults to 500.
    def test_brave_web_search_monthly_limit_defaults_to_500(self):
        os.environ.pop("BRAVE_WEB_SEARCH_MONTHLY_LIMIT", None)

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            allowed, remaining, limit = llm_daily_limit.consume_brave_web_search_monthly_quota(
                current_month="2026-02"
            )

        self.assertTrue(allowed)
        self.assertEqual(limit, 500)
        self.assertEqual(remaining, 499)


if __name__ == "__main__":
    unittest.main()
