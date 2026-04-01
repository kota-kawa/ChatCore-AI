import unittest

from services.chat_contract import (
    API_DATETIME_SERIALIZATION,
    API_FRONTEND_INTERNAL_CASE,
    API_REQUEST_CASE,
    API_RESPONSE_CASE,
    CHAT_HISTORY_PAGE_SIZE_DEFAULT,
    CHAT_HISTORY_PAGE_SIZE_MAX,
)


class ChatContractTestCase(unittest.TestCase):
    def test_chat_history_limits_are_loaded_from_contract(self):
        self.assertEqual(CHAT_HISTORY_PAGE_SIZE_DEFAULT, 50)
        self.assertEqual(CHAT_HISTORY_PAGE_SIZE_MAX, 100)
        self.assertGreaterEqual(CHAT_HISTORY_PAGE_SIZE_MAX, CHAT_HISTORY_PAGE_SIZE_DEFAULT)

    def test_case_and_datetime_conventions_are_declared(self):
        self.assertEqual(API_REQUEST_CASE, "snake_case")
        self.assertEqual(API_RESPONSE_CASE, "snake_case")
        self.assertEqual(API_FRONTEND_INTERNAL_CASE, "camelCase")
        self.assertEqual(API_DATETIME_SERIALIZATION, "iso-8601")


if __name__ == "__main__":
    unittest.main()
