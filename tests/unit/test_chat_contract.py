import unittest

from services.chat_contract import (
    API_DATETIME_SERIALIZATION,
    API_FRONTEND_INTERNAL_CASE,
    API_REQUEST_CASE,
    API_RESPONSE_CASE,
    CHAT_HISTORY_PAGE_SIZE_DEFAULT,
    CHAT_HISTORY_PAGE_SIZE_MAX,
)


# チャット履歴取得時のデフォルト・最大ページサイズ制限や、APIリクエスト・レスポンスの命名規則（ケース）の定義を検証するテストクラス。
# Test class to check definitions of default/max page size limits and case naming conventions for API requests and responses.
class ChatContractTestCase(unittest.TestCase):
    # チャット履歴取得ページサイズの上限値とデフォルト値の定義が妥当であることを検証します。
    # Verify that chat history page size limits are correctly defined and valid.
    def test_chat_history_limits_are_loaded_from_contract(self):
        self.assertEqual(CHAT_HISTORY_PAGE_SIZE_DEFAULT, 50)
        self.assertEqual(CHAT_HISTORY_PAGE_SIZE_MAX, 100)
        self.assertGreaterEqual(CHAT_HISTORY_PAGE_SIZE_MAX, CHAT_HISTORY_PAGE_SIZE_DEFAULT)

    # リクエスト/レスポンス、フロントエンド内部の変数命名規則、および日付時間のシリアライズ形式の定義を確認します。
    # Verify that naming conventions and datetime serialization formats are declared correctly in the contract.
    def test_case_and_datetime_conventions_are_declared(self):
        self.assertEqual(API_REQUEST_CASE, "snake_case")
        self.assertEqual(API_RESPONSE_CASE, "snake_case")
        self.assertEqual(API_FRONTEND_INTERNAL_CASE, "camelCase")
        self.assertEqual(API_DATETIME_SERIALIZATION, "iso-8601")


if __name__ == "__main__":
    unittest.main()
