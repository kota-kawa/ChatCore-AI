import unittest
from datetime import datetime

from services.datetime_serialization import serialize_datetime_iso


# 日本語: DateTimeSerializationTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to DateTimeSerializationTestCase.
class DateTimeSerializationTestCase(unittest.TestCase):
    # 日本語: test serialize datetime iso returns none for none のテスト検証を担当します。
    # English: Handle verifying test behavior for test serialize datetime iso returns none for none.
    def test_serialize_datetime_iso_returns_none_for_none(self):
        self.assertIsNone(serialize_datetime_iso(None))

    # 日本語: test serialize datetime iso returns iso8601 string のテスト検証を担当します。
    # English: Handle verifying test behavior for test serialize datetime iso returns iso8601 string.
    def test_serialize_datetime_iso_returns_iso8601_string(self):
        value = datetime(2024, 1, 2, 3, 4, 5)
        self.assertEqual(serialize_datetime_iso(value), "2024-01-02T03:04:05")


if __name__ == "__main__":
    unittest.main()
