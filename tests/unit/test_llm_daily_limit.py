import os
import unittest
from unittest.mock import patch

from services import llm_daily_limit


class LlmDailyLimitTestCase(unittest.TestCase):
    """
    LLM利用回数制限やメール送信制限、各種月間API制限などのクォータ制限機能を検証するテストクラス。
    Test case class to verify the functionality of daily/monthly API quota limits, including LLM and email send limits.
    """

    def setUp(self):
        """
        テスト実行前の準備として、環境変数を退避させ、メモリ内の制限状態カウンターをクリアします。
        Save the current environment variables and clear the in-memory daily limit state before running each test.
        """
        self.original_limit = os.environ.get("LLM_DAILY_API_LIMIT")
        self.original_auth_email_limit = os.environ.get("AUTH_EMAIL_DAILY_SEND_LIMIT")
        self.original_ai_agent_limit = os.environ.get("AI_AGENT_MONTHLY_API_LIMIT")
        self.original_brave_search_limit = os.environ.get("BRAVE_WEB_SEARCH_MONTHLY_LIMIT")
        llm_daily_limit.clear_in_memory_daily_limit_state()

    def tearDown(self):
        """
        テスト実行後の後処理として、退避していた環境変数を復元し、メモリ内の制限状態カウンターを再度クリアします。
        Restore the original environment variables and clear the in-memory daily limit state after running each test.
        """
        # LLM_DAILY_API_LIMIT 環境変数の復元
        # Restore LLM_DAILY_API_LIMIT environment variable
        if self.original_limit is None:
            os.environ.pop("LLM_DAILY_API_LIMIT", None)
        else:
            os.environ["LLM_DAILY_API_LIMIT"] = self.original_limit

        # AUTH_EMAIL_DAILY_SEND_LIMIT 環境変数の復元
        # Restore AUTH_EMAIL_DAILY_SEND_LIMIT environment variable
        if self.original_auth_email_limit is None:
            os.environ.pop("AUTH_EMAIL_DAILY_SEND_LIMIT", None)
        else:
            os.environ["AUTH_EMAIL_DAILY_SEND_LIMIT"] = self.original_auth_email_limit

        # AI_AGENT_MONTHLY_API_LIMIT 環境変数の復元
        # Restore AI_AGENT_MONTHLY_API_LIMIT environment variable
        if self.original_ai_agent_limit is None:
            os.environ.pop("AI_AGENT_MONTHLY_API_LIMIT", None)
        else:
            os.environ["AI_AGENT_MONTHLY_API_LIMIT"] = self.original_ai_agent_limit

        # BRAVE_WEB_SEARCH_MONTHLY_LIMIT 環境変数の復元
        # Restore BRAVE_WEB_SEARCH_MONTHLY_LIMIT environment variable
        if self.original_brave_search_limit is None:
            os.environ.pop("BRAVE_WEB_SEARCH_MONTHLY_LIMIT", None)
        else:
            os.environ["BRAVE_WEB_SEARCH_MONTHLY_LIMIT"] = self.original_brave_search_limit

        # メモリ内のキャッシュステートをクリーンアップ
        # Clean up the cache state in memory
        llm_daily_limit.clear_in_memory_daily_limit_state()

    def test_custom_limit_blocks_after_reaching_cap(self):
        """
        LLMの1日あたり利用制限に達した後、追加のリクエストがブロックされることを検証します。
        Verify that request is blocked after reaching the daily LLM API limit.
        """
        # クォータ上限を2回に設定
        # Set daily API limit to 2
        os.environ["LLM_DAILY_API_LIMIT"] = "2"

        # Redisが使えない環境（フォールバックとしてオンメモリ管理）での動作を検証
        # Mock redis connection to test in-memory fallback mechanism
        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            first = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")
            second = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")
            third = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")

        # 1回目と2回目は成功し、3回目はブロックされることを検証
        # Assert that the 1st and 2nd requests are allowed, but the 3rd is blocked
        self.assertEqual(first, (True, 1, 2))
        self.assertEqual(second, (True, 0, 2))
        self.assertEqual(third, (False, 0, 2))

    def test_counter_resets_on_next_day(self):
        """
        日付が変わると、LLMの1日あたり利用制限のカウンターがリセットされることを検証します。
        Verify that the LLM limit counter resets when the date changes.
        """
        # クォータ上限を1回に設定
        # Set daily limit to 1
        os.environ["LLM_DAILY_API_LIMIT"] = "1"

        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            day1 = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")
            day1_exceeded = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")
            # 日付が変わったタイミングでのリクエスト
            # Request after the date changes to the next day
            day2 = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-27")

        # 1日目は1回のみ許可、2日目はリセットされて再度許可されることを検証
        # Assert that only 1 request is allowed on Day 1, and Day 2 is reset and allowed
        self.assertEqual(day1, (True, 0, 1))
        self.assertEqual(day1_exceeded, (False, 0, 1))
        self.assertEqual(day2, (True, 0, 1))

    def test_invalid_env_value_falls_back_to_default(self):
        """
        環境変数に不正な値（数値以外）が設定されている場合、デフォルト値にフォールバックされることを検証します。
        Verify that invalid values in the environment variable fall back to the default limit.
        """
        # 不正な数値を設定
        # Set an invalid non-numeric limit string
        os.environ["LLM_DAILY_API_LIMIT"] = "not-a-number"

        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            allowed, remaining, limit = llm_daily_limit.consume_llm_daily_quota(current_date="2026-02-26")

        # デフォルトの上限値が適用されていることを検証
        # Assert that the default limit is applied
        self.assertTrue(allowed)
        self.assertEqual(limit, llm_daily_limit.DEFAULT_LLM_DAILY_API_LIMIT)
        self.assertEqual(remaining, llm_daily_limit.DEFAULT_LLM_DAILY_API_LIMIT - 1)

    def test_auth_email_limit_blocks_after_reaching_cap(self):
        """
        認証用メールの送信数が1日の制限に達した際、それ以上の送信が制限されることを検証します。
        Verify that daily auth email sending is blocked after reaching the daily send limit.
        """
        # 送信上限を2回に設定
        # Set daily send limit to 2
        os.environ["AUTH_EMAIL_DAILY_SEND_LIMIT"] = "2"

        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            first = llm_daily_limit.consume_auth_email_daily_quota(current_date="2026-02-26")
            second = llm_daily_limit.consume_auth_email_daily_quota(current_date="2026-02-26")
            third = llm_daily_limit.consume_auth_email_daily_quota(current_date="2026-02-26")

        # 3回目の送信要求がブロックされることを検証
        # Assert that the 3rd request is blocked
        self.assertEqual(first, (True, 1, 2))
        self.assertEqual(second, (True, 0, 2))
        self.assertEqual(third, (False, 0, 2))

    def test_ai_agent_monthly_limit_blocks_after_reaching_cap(self):
        """
        AIエージェントの月間呼び出し制限に達した際、追加のリクエストがブロックされることを検証します。
        Verify that AI agent requests are blocked after reaching the monthly limit.
        """
        # 月間制限上限を2回に設定
        # Set monthly limit to 2
        os.environ["AI_AGENT_MONTHLY_API_LIMIT"] = "2"

        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            first = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-02")
            second = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-02")
            third = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-02")

        # 3回目の要求がブロックされることを検証
        # Assert that the 3rd request is blocked
        self.assertEqual(first, (True, 1, 2))
        self.assertEqual(second, (True, 0, 2))
        self.assertEqual(third, (False, 0, 2))

    def test_ai_agent_monthly_counter_resets_on_next_month(self):
        """
        月が変わると、AIエージェントの月間制限カウンターが正しくリセットされることを検証します。
        Verify that the monthly AI agent limit counter resets on the next month.
        """
        # 月間制限上限を1回に設定
        # Set monthly limit to 1
        os.environ["AI_AGENT_MONTHLY_API_LIMIT"] = "1"

        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            month1 = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-02")
            month1_exceeded = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-02")
            # 翌月へ進めたタイミングでのリクエスト
            # Request after moving to the next month
            month2 = llm_daily_limit.consume_ai_agent_monthly_quota(current_month="2026-03")

        # 翌月にリセットされて再度許可されることを検証
        # Assert reset occurs in the next month, allowing request again
        self.assertEqual(month1, (True, 0, 1))
        self.assertEqual(month1_exceeded, (False, 0, 1))
        self.assertEqual(month2, (True, 0, 1))

    def test_brave_web_search_monthly_limit_blocks_after_reaching_cap(self):
        """
        Brave Web検索の月間制限に達した際、追加の検索要求がブロックされることを検証します。
        Verify that Brave web search requests are blocked after reaching the monthly limit.
        """
        # 月間上限を2回に設定
        # Set monthly search limit to 2
        os.environ["BRAVE_WEB_SEARCH_MONTHLY_LIMIT"] = "2"

        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            first = llm_daily_limit.consume_brave_web_search_monthly_quota(current_month="2026-02")
            second = llm_daily_limit.consume_brave_web_search_monthly_quota(current_month="2026-02")
            third = llm_daily_limit.consume_brave_web_search_monthly_quota(current_month="2026-02")

        # 3回目の検索要求がブロックされることを検証
        # Assert that the 3rd search request is blocked
        self.assertEqual(first, (True, 1, 2))
        self.assertEqual(second, (True, 0, 2))
        self.assertEqual(third, (False, 0, 2))

    def test_per_user_quota_does_not_drain_other_users(self):
        """
        特定のユーザーのクォータ制限到達が、他のユーザーの残クォータに影響を及ぼさないことを検証します。
        Verify that a quota consumption by one user does not drain or affect other users' quotas.
        """
        # 上限を2回に設定
        # Set daily limit to 2
        os.environ["LLM_DAILY_API_LIMIT"] = "2"

        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            # ユーザー1が制限に達するまで消費
            # User 1 consumes until hitting the limit
            a1 = llm_daily_limit.consume_llm_daily_quota(
                current_date="2026-02-26", user_key="user:1"
            )
            a2 = llm_daily_limit.consume_llm_daily_quota(
                current_date="2026-02-26", user_key="user:1"
            )
            a3 = llm_daily_limit.consume_llm_daily_quota(
                current_date="2026-02-26", user_key="user:1"
            )
            # ユーザー2はまだ制限に達していないため消費可能であることを確認
            # Assert that user 2 still has a fresh budget despite user 1 being capped
            b1 = llm_daily_limit.consume_llm_daily_quota(
                current_date="2026-02-26", user_key="user:2"
            )
            b2 = llm_daily_limit.consume_llm_daily_quota(
                current_date="2026-02-26", user_key="user:2"
            )

        # 結果を検証
        # Assert all results
        self.assertEqual(a1, (True, 1, 2))
        self.assertEqual(a2, (True, 0, 2))
        self.assertEqual(a3, (False, 0, 2))
        self.assertEqual(b1, (True, 1, 2))
        self.assertEqual(b2, (True, 0, 2))

    def test_brave_web_search_monthly_limit_defaults_to_500(self):
        """
        Brave Web検索の月間制限環境変数が未設定の場合、デフォルトの上限値 500 に設定されることを検証します。
        Verify that Brave web search monthly limit defaults to 500 when the environment variable is not set.
        """
        # 環境変数を削除
        # Pop the environment variable to test default behavior
        os.environ.pop("BRAVE_WEB_SEARCH_MONTHLY_LIMIT", None)

        with patch("services.llm_daily_limit.get_redis_client", return_value=None):
            allowed, remaining, limit = llm_daily_limit.consume_brave_web_search_monthly_quota(
                current_month="2026-02"
            )

        # デフォルトの上限値が500であることを検証
        # Assert that the limit defaults to 500
        self.assertTrue(allowed)
        self.assertEqual(limit, 500)
        self.assertEqual(remaining, 499)


if __name__ == "__main__":
    # テストを実行します
    # Execute the tests
    unittest.main()
